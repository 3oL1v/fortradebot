#!/bin/bash
echo "Устанавливаю зависимости..."
pip install -r backend/requirements.txt
echo "Запускаю сервер..."
uvicorn backend.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
