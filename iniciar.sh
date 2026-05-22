#!/bin/bash
echo "===================================="
echo "  FEFO WMS Control - Iniciando..."
echo "===================================="

if ! command -v python3 &> /dev/null; then
    echo "ERRO: Python3 não encontrado. Instale com: sudo apt install python3 python3-pip"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt -q

IP=$(hostname -I | awk '{print $1}')

echo ""
echo "===================================="
echo " Sistema iniciado!"
echo " http://localhost:8000"
echo " http://$IP:8000  (outros PCs da rede)"
echo "===================================="
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
