import android.system.Os;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.security.Key;
import java.security.KeyStore;
import java.util.Arrays;
import java.util.Base64;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

public class ExtractToken {
    public static void main(String[] args) {
        try {
            Class<?> providerClass = Class.forName("android.security.keystore2.AndroidKeyStoreProvider");
            providerClass.getMethod("install").invoke(null);

            // Default UID for com.nth.swisspost if not passed
            int uid = 10230;
            if (args.length > 0) {
                try {
                    uid = Integer.parseInt(args[0]);
                } catch (Exception ignored) {}
            }
            Os.setgid(uid);
            Os.setuid(uid);

            KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
            ks.load(null);
            Key masterKey = ks.getKey("_androidx_security_master_key_", null);

            File prefsDir = new File("/data/data/com.nth.swisspost/shared_prefs");
            File[] files = prefsDir.listFiles();
            if (files == null) {
                System.out.println("No preference files found in " + prefsDir);
                return;
            }

            for (File prefFile : files) {
                if (!prefFile.getName().endsWith(".xml")) continue;

                BufferedReader reader = new BufferedReader(new FileReader(prefFile));
                String line;
                String keysetHex = null;
                java.util.Map<String, String> entries = new java.util.HashMap<>();

                Pattern p = Pattern.compile("<string name=\"([^\"]+)\">([^<]+)</string>");
                while ((line = reader.readLine()) != null) {
                    Matcher m = p.matcher(line.trim());
                    if (m.matches()) {
                        String name = m.group(1);
                        String val = m.group(2);
                        if (name.equals("__androidx_security_crypto_encrypted_prefs_value_keyset__")) {
                            keysetHex = val;
                        } else if (!name.contains("keyset")) {
                            entries.put(name, val);
                        }
                    }
                }
                reader.close();

                if (keysetHex == null || entries.isEmpty()) {
                    continue;
                }

                byte[] rawKeyset = hexToBytes(keysetHex);
                int offset = 1;
                int len = 0;
                int shift = 0;
                while ((rawKeyset[offset] & 0x80) != 0) {
                    len |= (rawKeyset[offset] & 0x7f) << shift;
                    shift += 7;
                    offset++;
                }
                len |= (rawKeyset[offset] & 0x7f) << shift;
                offset++;

                byte[] encKeyset = Arrays.copyOfRange(rawKeyset, offset, offset + len);
                byte[] iv = Arrays.copyOfRange(encKeyset, 0, 12);
                byte[] ciphertext = Arrays.copyOfRange(encKeyset, 12, encKeyset.length);

                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, masterKey, new GCMParameterSpec(128, iv));
                byte[] decryptedKeyset = cipher.doFinal(ciphertext);

                // Find AES-256 Key
                String needle = "type.googleapis.com/google.crypto.tink.AesGcmKey";
                byte[] needleBytes = needle.getBytes();
                int keyIdx = -1;
                for (int i = 0; i < decryptedKeyset.length - needleBytes.length; i++) {
                    boolean match = true;
                    for (int j = 0; j < needleBytes.length; j++) {
                        if (decryptedKeyset[i+j] != needleBytes[j]) { match = false; break; }
                    }
                    if (match) { keyIdx = i + needleBytes.length; break; }
                }

                byte[] aesKey = null;
                for (int i = keyIdx; i < decryptedKeyset.length - 34; i++) {
                    if (decryptedKeyset[i] == 0x1a && decryptedKeyset[i+1] == 0x20) {
                        aesKey = Arrays.copyOfRange(decryptedKeyset, i + 2, i + 2 + 32);
                        break;
                    }
                }

                if (aesKey == null) continue;

                for (java.util.Map.Entry<String, String> entry : entries.entrySet()) {
                    String encKeyName = entry.getKey();
                    String encValB64 = entry.getValue();
                    try {
                        byte[] rawVal = Base64.getDecoder().decode(encValB64);
                        byte[] valIv = Arrays.copyOfRange(rawVal, 5, 5 + 12);
                        byte[] valCt = Arrays.copyOfRange(rawVal, 5 + 12, rawVal.length);
                        Cipher valCipher = Cipher.getInstance("AES/GCM/NoPadding");
                        SecretKeySpec valKey = new SecretKeySpec(aesKey, "AES");
                        valCipher.init(Cipher.DECRYPT_MODE, valKey, new GCMParameterSpec(128, valIv));
                        valCipher.updateAAD(encKeyName.getBytes("UTF-8"));
                        byte[] pt = valCipher.doFinal(valCt);
                        String strVal = new String(pt, "UTF-8");
                        if (strVal.contains("refreshToken")) {
                            System.out.println("AUTH_JSON_START");
                            System.out.println(strVal.substring(strVal.indexOf('{')));
                            System.out.println("AUTH_JSON_END");
                        }
                    } catch (Exception ignored) {}
                }
            }
        } catch (Throwable t) {
            t.printStackTrace(System.out);
        }
    }

    private static byte[] hexToBytes(String s) {
        int len = s.length();
        byte[] data = new byte[len / 2];
        for (int i = 0; i < len; i += 2) {
            data[i / 2] = (byte) ((Character.digit(s.charAt(i), 16) << 4)
                                 + Character.digit(s.charAt(i+1), 16));
        }
        return data;
    }
}
