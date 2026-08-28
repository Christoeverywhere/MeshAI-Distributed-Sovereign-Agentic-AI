# MeshAI — Distributed Sovereign Agentic AI

MeshAI is an air-gapped, local-first distributed AI system coordinating trusted smartphones, laptops, and GPU machines to execute multi-modal AI workloads without reliance on external cloud services.

## Current Stage: Step 1 — Node Network Orchestrator

For full documentation, architecture diagrams, manual testing instructions, and API references, see:
- [Orchestrator Documentation](file:///d:/MeshAI/orchestrator/README.md)

### Quick Start (Windows)
```powershell
cd d:\MeshAI
python -m venv .venv
.venv\Scripts\activate
pip install -r orchestrator\requirements.txt
uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000
```
API Documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
