"""Fake Worker Node Simulator for MeshAI.

Simulates an Android worker device connecting to the MeshAI Orchestrator.
Registers itself upon launch, periodically sends heartbeat pings, and cleanly
handles termination via Ctrl+C.
"""

import argparse
import logging
import sys
import time
from typing import List
import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fake_worker")


def parse_capabilities(cap_str: str) -> List[str]:
    """Split comma-separated capability list."""
    if not cap_str:
        return []
    return [c.strip().lower() for c in cap_str.split(",") if c.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="MeshAI Fake Worker Node Simulator"
    )
    parser.add_argument(
        "--node-id",
        type=str,
        required=True,
        help="Unique identifier for this worker node (e.g. phone_01)",
    )
    parser.add_argument(
        "--device-name",
        type=str,
        default="Simulated Android Device",
        help="Human-readable device model name",
    )
    parser.add_argument(
        "--device-type",
        type=str,
        default="android",
        help="Device platform type (default: android)",
    )
    parser.add_argument(
        "--os",
        dest="operating_system",
        type=str,
        default="Android 14",
        help="Operating system string",
    )
    parser.add_argument(
        "--ram",
        dest="ram_mb",
        type=int,
        default=8192,
        help="Total RAM in MB (default: 8192)",
    )
    parser.add_argument(
        "--cores",
        dest="cpu_cores",
        type=int,
        default=8,
        help="CPU cores count (default: 8)",
    )
    parser.add_argument(
        "--battery",
        dest="battery_percent",
        type=int,
        default=85,
        help="Initial battery percentage (default: 85)",
    )
    parser.add_argument(
        "--capabilities",
        type=str,
        default="ocr,vision",
        help="Comma-separated AI capabilities (e.g. 'ocr,vision,llm')",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port worker listens on (default: 8080)",
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default="http://127.0.0.1:8000",
        help="MeshAI Orchestrator base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3,
        help="Heartbeat interval in seconds (default: 3)",
    )

    args = parser.parse_args()
    capabilities = parse_capabilities(args.capabilities)
    base_url = args.server_url.rstrip("/")

    logger.info(f"Starting Fake Worker Node: {args.node_id} ({args.device_name})")
    logger.info(f"Target Orchestrator: {base_url}")
    logger.info(f"Capabilities: {capabilities}")
    logger.info(f"RAM: {args.ram_mb} MB | Cores: {args.cpu_cores}")

    # Step 1: Register with MeshAI Orchestrator
    reg_payload = {
        "node_id": args.node_id,
        "device_name": args.device_name,
        "device_type": args.device_type,
        "operating_system": args.operating_system,
        "ram_mb": args.ram_mb,
        "cpu_cores": args.cpu_cores,
        "battery_percent": args.battery_percent,
        "capabilities": capabilities,
        "port": args.port,
    }

    reg_url = f"{base_url}/api/v1/nodes/register"
    try:
        logger.info(f"Registering with orchestrator at {reg_url}...")
        resp = requests.post(reg_url, json=reg_payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            f"Registration successful! Status: {data.get('status')} | Message: {data.get('message')}"
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to register with orchestrator: {e}")
        sys.exit(1)

    # Step 2: Periodic Heartbeat Loop
    heartbeat_url = f"{base_url}/api/v1/nodes/{args.node_id}/heartbeat"
    current_battery = args.battery_percent
    heartbeat_count = 0

    logger.info(
        f"Entering heartbeat loop (sending heartbeat every {args.interval}s). Press Ctrl+C to stop."
    )

    try:
        while True:
            time.sleep(args.interval)
            heartbeat_count += 1

            # Simulate gradual battery drain every 10 heartbeats
            if heartbeat_count % 10 == 0 and current_battery > 5:
                current_battery -= 1

            hb_payload = {"battery_percent": current_battery}

            try:
                hb_resp = requests.post(
                    heartbeat_url, json=hb_payload, timeout=3
                )
                if hb_resp.status_code == 200:
                    logger.info(
                        f"Heartbeat #{heartbeat_count} sent (Battery: {current_battery}%) -> Status: ONLINE"
                    )
                else:
                    logger.warning(
                        f"Heartbeat #{heartbeat_count} returned status {hb_resp.status_code}: {hb_resp.text}"
                    )
            except requests.exceptions.RequestException as e:
                logger.warning(f"Heartbeat #{heartbeat_count} failed to send: {e}")

    except KeyboardInterrupt:
        logger.info(f"Worker {args.node_id} shutting down gracefully (Ctrl+C).")
        sys.exit(0)


if __name__ == "__main__":
    main()
