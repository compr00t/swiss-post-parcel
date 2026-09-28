"""Constants for Swiss Post integration."""

DOMAIN = "swiss_post"

# Configuration keys
CONF_ACCOUNT_NAME = "account_name"
CONF_AUTH_TYPE = "auth_type"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SESSION_COOKIES = "session_cookies"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_TOKEN_ENDPOINT = "token_endpoint"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEVICE_ID = "device_id"
CONF_ID_TOKEN = "id_token"
CONF_PROFILE_ID = "profile_id"

# Auth types
AUTH_TYPE_REFRESH_TOKEN = "refresh_token"
AUTH_TYPE_COOKIES = "cookies"

# Defaults
DEFAULT_ACCOUNT_NAME = "Personal"
DEFAULT_SCAN_INTERVAL = 15  # minutes
DEFAULT_CLIENT_ID = "swisspost_main_prod"
DEFAULT_TOKEN_ENDPOINT = "https://login.swissid.ch:443/idp/oauth2/access_token"

# Attributes
ATTR_PACKETS = "packets"
ATTR_COUNT = "count"
ATTR_IS_OUT_FOR_DELIVERY = "is_out_for_delivery"
ATTR_ESTIMATED_TIMESTAMP = "estimated_delivery_timestamp"
ATTR_ESTIMATED_WINDOW = "estimated_delivery_window"
ATTR_DELIVERY_DATE = "delivery_date"
ATTR_TRACKING_NUMBER = "tracking_number"
ATTR_FORMATTED_NUMBER = "formatted_number"
ATTR_SENDER = "sender"
ATTR_RECIPIENT = "recipient"
ATTR_STATUS = "status"
ATTR_STATE_SUMMARY = "state_summary"
ATTR_ACCOUNT = "account"
ATTR_TRACKING_URL = "tracking_url"
ATTR_OUT_FOR_DELIVERY_COUNT = "out_for_delivery_count"
ATTR_IN_TRANSIT_COUNT = "in_transit_count"
