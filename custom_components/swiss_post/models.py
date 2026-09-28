"""Data models for Swiss Post consignments in Home Assistant."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional


@dataclass
class Address:
    """Address details for sender or recipient."""
    name1: Optional[str] = None
    name2: Optional[str] = None
    name3: Optional[str] = None
    street: Optional[str] = None
    number: Optional[str] = None
    zip: Optional[str] = None
    city: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Address":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            name1=data.get("name1"),
            name2=data.get("name2"),
            name3=data.get("name3"),
            street=data.get("street"),
            number=data.get("number"),
            zip=data.get("zip"),
            city=data.get("city"),
        )

    @property
    def full_name(self) -> str:
        names = [n for n in [self.name1, self.name2, self.name3] if n]
        return " ".join(names) if names else ""

    @property
    def full_address(self) -> str:
        parts = []
        name = self.full_name
        if name:
            parts.append(name)
        street_part = " ".join([p for p in [self.street, self.number] if p])
        if street_part:
            parts.append(street_part)
        city_part = " ".join([p for p in [self.zip, self.city] if p])
        if city_part:
            parts.append(city_part)
        return ", ".join(parts)

    def __str__(self) -> str:
        return self.full_address or "Unknown"


@dataclass
class DeliveryTimeInterval:
    """Estimated delivery time interval."""
    start: Optional[str] = None
    end: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DeliveryTimeInterval":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            start=str(data.get("start")) if data.get("start") is not None else None,
            end=str(data.get("end")) if data.get("end") is not None else None,
        )

    @property
    def window_str(self) -> Optional[str]:
        if self.start and self.end:
            return f"{self.start} - {self.end}"
        if self.start:
            return f"From {self.start}"
        if self.end:
            return f"Until {self.end}"
        return None


@dataclass
class Shipment:
    """Represents a Swiss Post consignment."""
    identity: str
    shipment_number: str
    formatted_number: Optional[str] = None
    source: str = "PARCEL"  # PARCEL or LETTER
    global_status: str = "UNKNOWN"
    status: Optional[str] = None
    additional_status: Optional[str] = None
    description: Optional[str] = None
    is_delivered: bool = False
    is_returned: bool = False
    account_name: Optional[str] = None

    calculated_delivery_date: Optional[datetime] = None
    delivery_date: Optional[datetime] = None
    sending_date: Optional[datetime] = None
    last_event_date: Optional[datetime] = None

    time_interval: DeliveryTimeInterval = field(default_factory=DeliveryTimeInterval)
    sender: Address = field(default_factory=Address)
    addressee: Address = field(default_factory=Address)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_dict(cls, data: Dict[str, Any], account_name: Optional[str] = None) -> "Shipment":
        if "shipment" in data and isinstance(data["shipment"], dict):
            data = data["shipment"]

        def parse_date(val: Any) -> Optional[datetime]:
            if not val:
                return None
            try:
                if isinstance(val, (int, float)):
                    # Milliseconds timestamp from Java / JS backend
                    return datetime.fromtimestamp(val / 1000.0)
                if isinstance(val, str):
                    clean_str = val.replace("Z", "+00:00")
                    # If date only format YYYY-MM-DD
                    if len(clean_str) == 10 and clean_str.count("-") == 2:
                        return datetime.fromisoformat(f"{clean_str}T00:00:00")
                    return datetime.fromisoformat(clean_str)
            except Exception:
                return None
            return None

        delivered_flag = bool(
            data.get("delivered")
            or data.get("globalStatus") == "DELIVERED"
        )

        interval = DeliveryTimeInterval.from_dict(data.get("deliveryTimeInterval"))

        sender_data = data.get("sender")
        if not sender_data and data.get("debitorDescription"):
            sender_data = {"name1": data.get("debitorDescription")}
        elif isinstance(sender_data, dict) and not (sender_data.get("name1") or sender_data.get("name2")) and data.get("debitorDescription"):
            sender_data = dict(sender_data)
            sender_data["name1"] = data.get("debitorDescription")

        return cls(
            identity=str(data.get("identity") or data.get("shipmentNumber") or ""),
            shipment_number=str(data.get("shipmentNumber") or ""),
            formatted_number=data.get("formattedShipmentNumber") or data.get("shipmentNumber"),
            source=data.get("source") or "PARCEL",
            global_status=data.get("globalStatus") or ("DELIVERED" if delivered_flag else "IN_TRANSIT"),
            status=data.get("status"),
            additional_status=data.get("additionalStatus"),
            description=data.get("description") or data.get("debitorDescription"),
            is_delivered=delivered_flag,
            is_returned=bool(data.get("returned")),
            account_name=account_name,
            calculated_delivery_date=parse_date(data.get("calculatedDeliveryDate")),
            delivery_date=parse_date(data.get("deliveryDate")),
            sending_date=parse_date(data.get("sendingDateTime")),
            last_event_date=parse_date(data.get("lastEventDateTime")),
            time_interval=interval,
            sender=Address.from_dict(sender_data),
            addressee=Address.from_dict(data.get("addressee")),
            raw=data,
        )

    @classmethod
    def from_mobserv_dict(cls, data: Dict[str, Any], account_name: Optional[str] = None) -> "Shipment":
        """Parse shipment item from Swiss Post mobile overview API."""
        mailpiece_id = str(data.get("mailpieceId") or "")
        status_type = data.get("mailpieceStatusType", "UNKNOWN")
        is_complete = bool(data.get("isComplete"))
        is_delivered = status_type == "DELIVERED" or is_complete
        is_returned = status_type == "RETURNED"

        ts_ms = data.get("statusTimestamp")
        status_dt = None
        if ts_ms and isinstance(ts_ms, (int, float)):
            try:
                status_dt = datetime.fromtimestamp(ts_ms / 1000.0)
            except Exception:
                pass

        delivery_addr_data = data.get("deliveryAddress") or {}
        addr_detail = delivery_addr_data.get("addressDetail") or {}

        addressee = Address(
            name1=addr_detail.get("name1"),
            name2=addr_detail.get("name2"),
            street=addr_detail.get("street"),
            number=addr_detail.get("houseNumber"),
            zip=addr_detail.get("zip4") or addr_detail.get("zip"),
            city=addr_detail.get("city"),
        )

        sender_desc = data.get("summaryDescription") or data.get("productName")
        sender = Address(name1=sender_desc)

        return cls(
            identity=mailpiece_id,
            shipment_number=mailpiece_id,
            formatted_number=mailpiece_id,
            source=data.get("mailpieceType") or "PARCEL",
            global_status=status_type,
            status=status_type,
            additional_status=data.get("productName"),
            description=data.get("summaryDescription"),
            is_delivered=is_delivered,
            is_returned=is_returned,
            account_name=account_name,
            calculated_delivery_date=status_dt if not is_delivered else None,
            delivery_date=status_dt if is_delivered else None,
            last_event_date=status_dt,
            sender=sender,
            addressee=addressee,
            raw=data,
        )

    @property
    def is_parcel(self) -> bool:
        return self.source.upper() == "PARCEL"

    @property
    def is_letter(self) -> bool:
        return self.source.upper() == "LETTER"

    @property
    def is_out_for_delivery(self) -> bool:
        """True if parcel is currently out for delivery today."""
        if self.is_delivered:
            return False
        if self.global_status in ("TO_BE_DELIVERED", "ON_GOING_DELIVERY"):
            return True
        status_str = f"{self.status or ''} {self.additional_status or ''}".lower()
        return "wird zugestellt" in status_str or "out for delivery" in status_str

    @property
    def estimated_delivery_window(self) -> Optional[str]:
        return self.time_interval.window_str

    @property
    def estimated_delivery_timestamp(self) -> Optional[datetime]:
        """Estimated datetime timestamp when out for delivery."""
        if not self.is_out_for_delivery:
            return self.calculated_delivery_date

        target_date = (
            self.calculated_delivery_date.date()
            if self.calculated_delivery_date
            else datetime.now().date()
        )

        # If start time is specified like "10:00" or "10:30"
        if self.time_interval.start:
            try:
                parts = self.time_interval.start.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                return datetime.combine(target_date, time(hour, minute))
            except Exception:
                pass

        return self.calculated_delivery_date

    @property
    def delivery_date_only(self) -> Optional[date]:
        """Delivery date as date object (YYYY-MM-DD)."""
        dt = self.calculated_delivery_date or self.delivery_date
        return dt.date() if dt else None

    @property
    def state_summary(self) -> str:
        if self.is_delivered:
            date_str = f" on {self.delivery_date.strftime('%Y-%m-%d %H:%M')}" if self.delivery_date else ""
            return f"Delivered{date_str}"
        if self.is_returned:
            return "Returned to sender"
        if self.is_out_for_delivery:
            window = f" ({self.estimated_delivery_window})" if self.estimated_delivery_window else ""
            return f"Out for delivery today{window}"
        if self.global_status == "WAITING_FOR_PICKUP":
            return "Ready for pickup"
        if self.global_status == "NOT_YET_SENT":
            return "Announced / Not yet sent"
        if self.calculated_delivery_date:
            return f"In transit (Est: {self.calculated_delivery_date.strftime('%Y-%m-%d')})"
        return self.status or self.global_status or "In transit"

    @property
    def tracking_url(self) -> str:
        clean_num = self.shipment_number.replace(" ", "")
        return f"https://www.post.ch/swisspost-tracking?formattedParcelCodes={clean_num}"

    def to_dict(self) -> Dict[str, Any]:
        """Dictionary for sensor state attributes."""
        dt_delivery = self.delivery_date or self.calculated_delivery_date
        return {
            "tracking_number": self.shipment_number,
            "formatted_number": self.formatted_number or self.shipment_number,
            "source": self.source,
            "status": self.status or self.global_status,
            "state_summary": self.state_summary,
            "is_out_for_delivery": self.is_out_for_delivery,
            "is_delivered": self.is_delivered,
            "delivery_date": self.delivery_date_only.isoformat() if self.delivery_date_only else None,
            "delivery_time_window": self.estimated_delivery_window,
            "estimated_delivery_timestamp": (
                self.estimated_delivery_timestamp.isoformat()
                if self.estimated_delivery_timestamp
                else None
            ),
            "sender": self.sender.full_name or self.sender.city or "Unknown",
            "recipient": self.addressee.full_name or self.addressee.city or "Unknown",
            "description": self.description,
            "account": self.account_name or "Default",
            "tracking_url": self.tracking_url,
        }
