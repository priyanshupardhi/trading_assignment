
## System Architecture Diagram


```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   DJANGO APP    │    │   REDIS PUB/SUB  │    │ FASTAPI ENGINE  │
│   (Exchange)    │────│     CHANNELS     │────│   (Matching)    │
├─────────────────┤    ├──────────────────┤    ├─────────────────┤
│ - Order CRUD    │    │ Channel: orders  │    │ - Order Book    │
│ - Trade Listing │    │ Channel: trades  │    │ - Trade Matching│
│ - Publish to    │    │                  │    │ - WebSockets    │
│   Redis on      │    │                  │    │ - Subscribe to  │
│   order actions │    │                  │    │   Redis         │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ TRADE CONSUMER  │    │   WEBSOCKET      │    │   CLIENT APPS   │
│ (Mgmt Command)  │    │   CONNECTIONS    │    │                 │
├─────────────────┤    ├──────────────────┤    ├─────────────────┤
│ - Listen to     │    │ - Trade Updates  │    │ - Real-time     │
│   trades channel│    │ - Order Book     │    │   Updates       │
│ - Create Trade  │    │   Snapshots      │    │ - Order         │
│   objects       │    │   (every second) │    │   Management    │
└─────────────────┘    └──────────────────┘    └─────────────────┘

```
