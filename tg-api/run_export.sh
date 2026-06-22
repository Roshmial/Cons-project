#!/bin/bash
python3 -m venv venv
source venv/bin/activate
pip install telethon pyyaml
python3 /home/hermes/workspace/TG-API/export_script.py
