# Swiss Post Integration for Home Assistant

Custom component for Home Assistant to track incoming and past parcels from Swiss Post (`service.post.ch`). Compatible with HACS.

## Features

- **Next Delivery Sensor**: Next incoming delivery date, plus estimated time window when out for delivery.
- **Estimated Timestamp Sensor**: Dedicated timestamp entity for scheduled delivery window.
- **Outstanding Packets Count**: Number of packages in transit or out for delivery.
- **Detailed Consignments Attribute List**: Structured shipment details (tracking numbers, sender, destination, status, tracking URLs).
- **Multi-Account Aggregation**: Supports multiple configured accounts with deduplication across consolidated sensors.
- **Authentication**: Supports OAuth refresh token (with automatic token renewal) and session cookie authentication.

## Installation

### HACS (Recommended)

1. Open **HACS** > **Integrations** > **Custom repositories**.
2. Add the repository URL with category **Integration**.
3. Search for **Swiss Post** and install.
4. Restart Home Assistant.

### Manual Installation

Copy `custom_components/swiss_post` to `<config_dir>/custom_components/swiss_post` and restart Home Assistant.

## Configuration

Add the integration via **Settings** > **Devices & Services** > **Add Integration** > **Swiss Post**.

| Field | Description |
|---|---|
| `Account Label` | Friendly identifier for the account (e.g., `Primary`, `Business`). |
| `Authentication Method` | `Refresh Token` (automatic renewal) or `Session Cookies`. |
| `Scan Interval` | Polling frequency in minutes (default: `15`). |

Multiple accounts can be configured by adding the integration again. Consignments across all accounts are merged into the consolidated sensors.

## Entities

### Consolidated Entities

| Entity ID | Device Class | Description |
|---|---|---|
| `sensor.swiss_post_next_delivery` | - | Date of next incoming delivery, or status/time window if out for delivery today. |
| `sensor.swiss_post_estimated_delivery_time` | `timestamp` | Estimated delivery datetime when out for delivery. |
| `sensor.swiss_post_outstanding_packets` | - | Integer count of packages currently in transit or out for delivery. |
| `sensor.swiss_post_outstanding_packets_list` | - | Summary state with full structured shipment data in the `packets` attribute. |

### Per-Account Entities

For each configured account `<account>`:
- `sensor.swiss_post_<account>_next_delivery`
- `sensor.swiss_post_<account>_outstanding_packets`
- `sensor.swiss_post_<account>_outstanding_packets_list`

### Attributes Schema (`packets`)

```yaml
packets:
  - tracking_number: "99.00.123456.12345678"
    formatted_number: "99.00.123456.12345678"
    sender: "Merchant Name"
    recipient: "Recipient Name"
    status: "TO_BE_DELIVERED"
    state_summary: "Out for delivery today (09:30 - 11:30)"
    is_out_for_delivery: true
    delivery_date: "2026-09-28"
    delivery_time_window: "09:30 - 11:30"
    estimated_delivery_timestamp: "2026-09-28T09:30:00"
    account: "Primary"
    tracking_url: "https://www.post.ch/swisspost-tracking?formattedParcelCodes=990012345612345678"
```

## Dashboard Card Example

```yaml
type: markdown
title: Swiss Post Deliveries
content: >
  **Next Delivery:** {{ states('sensor.swiss_post_next_delivery') }}
  {% if is_state_attr('sensor.swiss_post_next_delivery', 'is_out_for_delivery', true) %}
  Estimated window: {{ state_attr('sensor.swiss_post_next_delivery', 'estimated_delivery_window') }}
  {% endif %}

  ### Outstanding ({{ states('sensor.swiss_post_outstanding_packets') }}):
  {% for p in state_attr('sensor.swiss_post_outstanding_packets_list', 'packets') %}
  - **[{{ p.sender }}]({{ p.tracking_url }})** ({{ p.account }})
    - Status: {{ p.state_summary }}
    {% if p.delivery_time_window %}
    - Window: {{ p.delivery_time_window }}
    {% endif %}
  {% endfor %}
```

## Automation Example

```yaml
alias: "Swiss Post: Out For Delivery Notification"
trigger:
  - platform: state
    entity_id: sensor.swiss_post_next_delivery
    attribute: is_out_for_delivery
    to: true
action:
  - action: notify.notify
    data:
      title: "Swiss Post Delivery Today"
      message: >
        Parcel from {{ state_attr('sensor.swiss_post_next_delivery', 'sender') }} is out for delivery.
        Estimated window: {{ state_attr('sensor.swiss_post_next_delivery', 'estimated_delivery_window') or 'Today' }}.
      data:
        url: "{{ state_attr('sensor.swiss_post_next_delivery', 'tracking_url') }}"
```
