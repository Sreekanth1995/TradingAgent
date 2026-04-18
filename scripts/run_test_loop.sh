#!/bin/bash

echo "Starting CSV Simulation using simulate_webhook.py..."
echo "------------------------------------------------"
echo "Processing test_data.csv at $(date)"

python3 "$(dirname "$0")/../simulations/simulate_webhook.py"

echo -e "\nSimulation complete."


