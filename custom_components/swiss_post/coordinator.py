"""DataUpdateCoordinator for Swiss Post integration with multi-account consolidation."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import SwissPostAuthError, SwissPostClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import Shipment

_LOGGER = logging.getLogger(__name__)


class SwissPostConsolidatedData:
    """Consolidated state across all active accounts."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.coordinators: Dict[str, "SwissPostAccountCoordinator"] = {}
        self._listeners: Set[Callable[[], None]] = set()

        self.upcoming_packets: List[Shipment] = []
        self.past_packets: List[Shipment] = []
        self.next_delivery_packet: Optional[Shipment] = None
        self.is_out_for_delivery: bool = False
        self.estimated_delivery_timestamp: Optional[datetime] = None
        self.estimated_delivery_window: Optional[str] = None
        self.out_for_delivery_count: int = 0
        self.in_transit_count: int = 0
        self.total_outstanding: int = 0
        self.account_names: List[str] = []

    def register_coordinator(self, entry_id: str, coordinator: "SwissPostAccountCoordinator") -> None:
        self.coordinators[entry_id] = coordinator
        self.recalculate()

    def unregister_coordinator(self, entry_id: str) -> None:
        if entry_id in self.coordinators:
            del self.coordinators[entry_id]
            self.recalculate()

    def add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(update_callback)

        def remove_listener():
            self._listeners.discard(update_callback)

        return remove_listener

    @callback
    def recalculate(self) -> None:
        """Recalculate consolidated metrics across all accounts."""
        seen_numbers = set()
        all_upcoming: List[Shipment] = []
        all_past: List[Shipment] = []
        accounts = []

        for coord in self.coordinators.values():
            if not coord.data:
                continue
            accounts.append(coord.account_name)
            for s in coord.data.get("upcoming", []):
                if s.shipment_number not in seen_numbers:
                    seen_numbers.add(s.shipment_number)
                    all_upcoming.append(s)

            for s in coord.data.get("past", []):
                if s.shipment_number not in seen_numbers:
                    all_past.append(s)

        # Sort upcoming by earliest estimated delivery or event date
        all_upcoming.sort(
            key=lambda s: s.calculated_delivery_date or s.last_event_date or s.sending_date or datetime.max
        )

        self.upcoming_packets = all_upcoming
        self.past_packets = all_past
        self.total_outstanding = len(all_upcoming)
        self.account_names = accounts

        # Out for delivery check
        out_for_del = [s for s in all_upcoming if s.is_out_for_delivery]
        self.out_for_delivery_count = len(out_for_del)
        self.in_transit_count = self.total_outstanding - self.out_for_delivery_count
        self.is_out_for_delivery = bool(out_for_del)

        if all_upcoming:
            # If any package is out for delivery today, prioritize that as next delivery
            if out_for_del:
                # Soonest out for delivery
                out_for_del.sort(
                    key=lambda s: s.estimated_delivery_timestamp or s.calculated_delivery_date or datetime.max
                )
                self.next_delivery_packet = out_for_del[0]
            else:
                self.next_delivery_packet = all_upcoming[0]

            self.estimated_delivery_timestamp = self.next_delivery_packet.estimated_delivery_timestamp
            self.estimated_delivery_window = self.next_delivery_packet.estimated_delivery_window
        else:
            self.next_delivery_packet = None
            self.estimated_delivery_timestamp = None
            self.estimated_delivery_window = None

        _LOGGER.debug(
            "Consolidated Swiss Post: %s outstanding packets across %s accounts (Out for delivery: %s)",
            self.total_outstanding,
            len(self.account_names),
            self.is_out_for_delivery,
        )

        for listener in list(self._listeners):
            listener()


class SwissPostAccountCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator managing updates for a single Swiss Post account."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SwissPostClient,
    ) -> None:
        self.entry = entry
        self.client = client
        self.account_name = client.account_name

        interval_minutes = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"Swiss Post ({self.account_name})",
            update_interval=timedelta(minutes=interval_minutes),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch consignments from Swiss Post."""
        try:
            upcoming, past = await self.hass.async_add_executor_job(self.client.get_parcels)
            data = {
                "upcoming": upcoming,
                "past": past,
                "account_name": self.account_name,
            }

            # Trigger consolidated recalculation
            consolidator: SwissPostConsolidatedData = self.hass.data[DOMAIN].get("consolidator")
            if consolidator:
                consolidator.recalculate()

            return data

        except SwissPostAuthError as err:
            _LOGGER.error("[%s] Authentication failed: %s", self.account_name, err)
            raise ConfigEntryAuthFailed(err) from err
        except Exception as err:
            _LOGGER.error("[%s] Error fetching Swiss Post consignments: %s", self.account_name, err)
            raise UpdateFailed(f"Error fetching consignments: {err}") from err
