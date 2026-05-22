# FEFO WMS Control

Sistema de controle paralelo de **lote e validade** integrado aos endereços do WMS Bravium.
Garante separação por FEFO (First Expired, First Out) com banco de dados SQLite compartilhado na rede interna.

---

## Requisitos

- Python 3.10 ou superior → https://python.org/downloads
- Computador conectado à rede interna (qualquer SO: Windows, Linux, Mac)

---

## Instalação — Windows

1. Instale o Python (marque "Add to PATH" durante a instalação)
2. Extraia a pasta `fefo-wms` em qualquer lugar (ex: `C:\fefo-wms`)
3. Dê duplo clique em **`iniciar.bat`**
4. Aguarde a mensagem com o endereço de acesso

## Instalação — Linux / Mac

```bash
cd fefo-wms
chmod +x iniciar.sh
./iniciar.sh
```

---

## Acesso

| De onde | Endereço |
|---------|----------|
| Mesmo computador | http://localhost:8000 |
| Outros PCs da rede | http://[IP-DO-SERVIDOR]:8000 |

O IP do servidor aparece no terminal ao iniciar.

---

## Funcionalidades

### Dashboard
Visão geral: total de lotes, SKUs, endereços, alertas de vencimento e lotes críticos.

### Recebimento
Cadastro manual de lotes no momento da entrada:
- SKU, número do lote, data de validade
- Quantidade, unidade, endereço do WMS, fornecedor

### Estoque por endereço
Todos os lotes ordenados por validade (FEFO) com filtros por SKU, endereço e status.
Status automático:
- 🟢 **OK** — validade > 30 dias
- 🟡 **Atenção** — vence em até 30 dias
- 🔴 **Crítico** — vence em até 7 dias
- ⛔ **Vencido** — data ultrapassada

### Fila FEFO
Selecione um produto e a quantidade necessária.
O sistema calcula automaticamente:
- Qual lote separar primeiro (mais próximo do vencimento)
- Em qual endereço do WMS ele está
- Quantas unidades pegar de cada lote

### Movimentos
Histórico completo de entradas, saídas e ajustes com usuário e observação.

### Importar / Exportar
- Importe CSV exportado do WMS Bravium
- Cole diretamente texto CSV
- Exporte o estoque atual para backup

---

## Formato do CSV para importação

```
sku,descricao,lote,validade,quantidade,unidade,endereco,fornecedor
SKU-001,Leite UHT 1L,LOT-2025-01,2025-12-31,100,UN,A-01-01,Laticínios SA
SKU-002,Iogurte 170g,LOT-2025-05,2025-06-15,48,CX,B-03-02,Laticínios SA
```

**Colunas obrigatórias:** `sku`, `lote`, `validade` (formato YYYY-MM-DD), `quantidade`, `endereco`

---

## Banco de dados

O arquivo `fefo.db` é criado automaticamente na pasta do sistema.
Todos os usuários da rede que acessam o mesmo servidor compartilham o mesmo banco.

**Backup:** basta copiar o arquivo `fefo.db` periodicamente.

---

## Múltiplos usuários

Inicie o servidor em **um único computador** da rede.
Todos os outros acessam pelo navegador usando o IP desse computador.
Não é necessário instalar nada nos outros computadores.
