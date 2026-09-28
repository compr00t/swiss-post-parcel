"""Sensors for Swiss Post consignments integration."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ACCOUNT,
    ATTR_COUNT,
    ATTR_DELIVERY_DATE,
    ATTR_ESTIMATED_TIMESTAMP,
    ATTR_ESTIMATED_WINDOW,
    ATTR_FORMATTED_NUMBER,
    ATTR_IN_TRANSIT_COUNT,
    ATTR_IS_OUT_FOR_DELIVERY,
    ATTR_OUT_FOR_DELIVERY_COUNT,
    ATTR_PACKETS,
    ATTR_RECIPIENT,
    ATTR_SENDER,
    ATTR_STATUS,
    ATTR_TRACKING_NUMBER,
    ATTR_TRACKING_URL,
    DOMAIN,
)
from .coordinator import SwissPostAccountCoordinator, SwissPostConsolidatedData
from .models import Shipment

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Swiss Post sensors based on a config entry."""
    coordinator: SwissPostAccountCoordinator = hass.data[DOMAIN]["coordinators"][entry.entry_id]
    consolidator: SwissPostConsolidatedData = hass.data[DOMAIN]["consolidator"]

    entities: List[SensorEntity] = [
        # Per-account sensors
        SwissPostAccountNextDeliverySensor(coordinator, entry),
        SwissPostAccountOutstandingCountSensor(coordinator, entry),
        SwissPostAccountOutstandingListSensor(coordinator, entry),
    ]

    # Consolidated sensors (only register once across all entries)
    if not hass.data[DOMAIN].get("consolidated_entities_added"):
        hass.data[DOMAIN]["consolidated_entities_added"] = True
        entities.extend([
            SwissPostConsolidatedNextDeliverySensor(consolidator, hass),
            SwissPostConsolidatedEstimatedTimestampSensor(consolidator, hass),
            SwissPostConsolidatedOutstandingCountSensor(consolidator, hass),
            SwissPostConsolidatedOutstandingListSensor(consolidator, hass),
        ])

    async_add_entities(entities)


# -----------------------------------------------------------------------------
# CONSOLIDATED SENSORS (All Accounts Merged)
# -----------------------------------------------------------------------------

class SwissPostConsolidatedBaseSensor(SensorEntity):
    """Base sensor for consolidated Swiss Post data."""

    _attr_has_entity_name = True

    def __init__(self, consolidator: SwissPostConsolidatedData, hass: HomeAssistant) -> None:
        self.consolidator = consolidator
        self.hass = hass
        self._remove_listener = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "swiss_post_consolidated")},
            name="Swiss Post (All Accounts)",
            manufacturer="Swiss Post",
            model="Consolidated Consignments Tracker",
            entry_type=None,
        )

    async def async_added_to_hass(self) -> None:
        """Register listener when entity is added to hass."""
        await super().async_added_to_hass()
        self._remove_listener = self.consolidator.add_listener(self._handle_consolidator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Remove listener when entity is removed."""
        if self._remove_listener:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_consolidator_update(self) -> None:
        self.async_write_ha_state()


class SwissPostConsolidatedNextDeliverySensor(SwissPostConsolidatedBaseSensor):
    """Sensor exposing the date of the next delivery, or estimated timestamp if out for delivery."""

    _attr_name = "Next Delivery"
    _attr_icon = "mdi:truck-delivery"
    _attr_unique_id = "swiss_post_consolidated_next_delivery"

    @property
    def native_value(self) -> Optional[str]:
        packet = self.consolidator.next_delivery_packet
        if not packet:
            return None

        # If currently out for delivery and has estimated timestamp
        if self.consolidator.is_out_for_delivery and packet.is_out_for_delivery:
            if packet.estimated_delivery_timestamp:
                return packet.estimated_delivery_timestamp.isoformat()
            if packet.estimated_delivery_window:
                today = datetime.now().strftime("%Y-%m-%d")
                return f"{today} ({packet.estimated_delivery_window})"

        # Otherwise date of the next delivery
        if packet.delivery_date_only:
            return packet.delivery_date_only.isoformat()

        return packet.state_summary

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        packet = self.consolidator.next_delivery_packet
        if not packet:
            return {
                ATTR_IS_OUT_FOR_DELIVERY: False,
                ATTR_COUNT: 0,
            }

        return {
            ATTR_IS_OUT_FOR_DELIVERY: packet.is_out_for_delivery,
            ATTR_ESTIMATED_TIMESTAMP: (
                packet.estimated_delivery_timestamp.isoformat()
                if packet.estimated_delivery_timestamp
                else None
            ),
            ATTR_ESTIMATED_WINDOW: packet.estimated_delivery_window,
            ATTR_DELIVERY_DATE: packet.delivery_date_only.isoformat() if packet.delivery_date_only else None,
            ATTR_TRACKING_NUMBER: packet.shipment_number,
            ATTR_FORMATTED_NUMBER: packet.formatted_number or packet.shipment_number,
            ATTR_SENDER: packet.sender.full_name or packet.sender.city or "Unknown",
            ATTR_RECIPIENT: packet.addressee.full_name or packet.addressee.city or "Unknown",
            ATTR_STATUS: packet.status or packet.global_status,
            ATTR_ACCOUNT: packet.account_name or "Default",
            ATTR_TRACKING_URL: packet.tracking_url,
            "total_outstanding": self.consolidator.total_outstanding,
        }


class SwissPostConsolidatedEstimatedTimestampSensor(SwissPostConsolidatedBaseSensor):
    """Sensor specifically for the estimated delivery timestamp when out for delivery."""

    _attr_name = "Estimated Delivery Time"
    _attr_icon = "mdi:clock-delivery"
    _attr_unique_id = "swiss_post_consolidated_estimated_delivery_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> Optional[datetime]:
        packet = self.consolidator.next_delivery_packet
        if packet and packet.is_out_for_delivery and packet.estimated_delivery_timestamp:
            return packet.estimated_delivery_timestamp
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        packet = self.consolidator.next_delivery_packet
        if not packet or not packet.is_out_for_delivery:
            return {ATTR_IS_OUT_FOR_DELIVERY: False}

        return {
            ATTR_IS_OUT_FOR_DELIVERY: True,
            ATTR_ESTIMATED_WINDOW: packet.estimated_delivery_window,
            ATTR_TRACKING_NUMBER: packet.shipment_number,
            ATTR_SENDER: packet.sender.full_name or packet.sender.city or "Unknown",
            ATTR_ACCOUNT: packet.account_name or "Default",
        }


class SwissPostConsolidatedOutstandingCountSensor(SwissPostConsolidatedBaseSensor):
    """Sensor with the total number of outstanding packets across all accounts."""

    _attr_name = "Outstanding Packets"
    _attr_icon = "mdi:package-variant-closed"
    _attr_unique_id = "swiss_post_consolidated_outstanding_packets"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        return self.consolidator.total_outstanding

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            ATTR_OUT_FOR_DELIVERY_COUNT: self.consolidator.out_for_delivery_count,
            ATTR_IN_TRANSIT_COUNT: self.consolidator.in_transit_count,
            "accounts": self.consolidator.account_names,
        }


class SwissPostConsolidatedOutstandingListSensor(SwissPostConsolidatedBaseSensor):
    """Sensor with a list of all outstanding packets across all accounts."""

    _attr_name = "Outstanding Packets List"
    _attr_icon = "mdi:format-list-bulleted-type"
    _attr_unique_id = "swiss_post_consolidated_outstanding_packets_list"

    @property
    def native_value(self) -> str:
        count = self.consolidator.total_outstanding
        if count == 0:
            return "No outstanding packets"
        if count == 1:
            return "1 packet outstanding"
        return f"{count} packets outstanding"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            ATTR_COUNT: self.consolidator.total_outstanding,
            ATTR_PACKETS: [p.to_dict() for p in self.consolidator.upcoming_packets],
        }


# -----------------------------------------------------------------------------
# PER-ACCOUNT SENSORS
# -----------------------------------------------------------------------------

class SwissPostAccountBaseSensor(CoordinatorEntity[SwissPostAccountCoordinator], SensorEntity):
    """Base sensor for individual account metrics."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SwissPostAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.account_name = coordinator.account_name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=f"Swiss Post ({self.account_name})",
            manufacturer="Swiss Post",
            model="Customer Consignment Account",
        )


class SwissPostAccountNextDeliverySensor(SwissPostAccountBaseSensor):
    """Per-account next delivery sensor."""

    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: SwissPostAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Next Delivery"
        self._attr_unique_id = f"{entry.entry_id}_next_delivery"

    @property
    def native_value(self) -> Optional[str]:
        upcoming: List[Shipment] = self.coordinator.data.get("upcoming", []) if self.coordinator.data else []
        if not upcoming:
            return None

        out_for_del = [s for s in upcoming if s.is_out_for_delivery]
        target = out_for_del[0] if out_for_del else upcoming[0]

        if target.is_out_for_delivery:
            if target.estimated_delivery_timestamp:
                return target.estimated_delivery_timestamp.isoformat()
            if target.estimated_delivery_window:
                today = datetime.now().strftime("%Y-%m-%d")
                return f"{today} ({target.estimated_delivery_window})"

        if target.delivery_date_only:
            return target.delivery_date_only.isoformat()
        return target.state_summary

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        upcoming: List[Shipment] = self.coordinator.data.get("upcoming", []) if self.coordinator.data else []
        if not upcoming:
            return {ATTR_IS_OUT_FOR_DELIVERY: False, ATTR_COUNT: 0}

        out_for_del = [s for s in upcoming if s.is_out_for_delivery]
        target = out_for_del[0] if out_for_del else upcoming[0]

        return {
            ATTR_IS_OUT_FOR_DELIVERY: target.is_out_for_delivery,
            ATTR_ESTIMATED_TIMESTAMP: (
                target.estimated_delivery_timestamp.isoformat()
                if target.estimated_delivery_timestamp
                else None
            ),
            ATTR_ESTIMATED_WINDOW: target.estimated_delivery_window,
            ATTR_DELIVERY_DATE: target.delivery_date_only.isoformat() if target.delivery_date_only else None,
            ATTR_TRACKING_NUMBER: target.shipment_number,
            ATTR_FORMATTED_NUMBER: target.formatted_number or target.shipment_number,
            ATTR_SENDER: target.sender.full_name or target.sender.city or "Unknown",
            ATTR_RECIPIENT: target.addressee.full_name or target.addressee.city or "Unknown",
            ATTR_STATUS: target.status or target.global_status,
            ATTR_ACCOUNT: self.account_name,
            ATTR_TRACKING_URL: target.tracking_url,
        }


class SwissPostAccountOutstandingCountSensor(SwissPostAccountBaseSensor):
    """Per-account count of outstanding packets."""

    _attr_icon = "mdi:package-variant-closed"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SwissPostAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Outstanding Packets"
        self._attr_unique_id = f"{entry.entry_id}_outstanding_packets"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return len(self.coordinator.data.get("upcoming", []))


class SwissPostAccountOutstandingListSensor(SwissPostAccountBaseSensor):
    """Per-account list of outstanding packets."""

    _attr_icon = "mdi:format-list-bulleted-type"

    def __init__(self, coordinator: SwissPostAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Outstanding Packets List"
        self._attr_unique_id = f"{entry.entry_id}_outstanding_packets_list"

    @property
    def native_value(self) -> str:
        count = len(self.coordinator.data.get("upcoming", [])) if self.coordinator.data else 0
        if count == 0:
            return "No outstanding packets"
        if count == 1:
            return "1 packet outstanding"
        return f"{count} packets outstanding"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        upcoming = self.coordinator.data.get("upcoming", []) if self.coordinator.data else []
        return {
            ATTR_COUNT: len(upcoming),
            ATTR_PACKETS: [p.to_dict() for p in upcoming],
        }
