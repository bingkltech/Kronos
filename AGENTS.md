# AGENTS.md — Kronos Foundation & Quant Architecture Invariants

Welcome to the **Kronos** workspace. To preserve LLM context tokens, prevent costly credit burning, and maintain institutional-grade mathematical rigor, the orchestrator and all agents are strictly bound by these core laws:

---

## 1. Zero Float Financial Math
NEVER use IEEE 754 floating-point math (`float` in Python / `number` in JS) for financial accounting, order sizing, balances, fees, or execution PnL.
- **Python:** Always use `decimal.Decimal` (cast floats via string: `Decimal(str(price))`).
- **PyTorch Tensors:** Model weights and normalized features $(z \in \mathbb{R})$ use standard `torch.float32`, but real monetary values must be converted to `Decimal` upon output.

---

## 2. Kronos Context Slicing Contract
`Kronos-small` and `Kronos-base` have a hard context length ceiling of **512 tokens**.
- **Mandatory Tail-Slicing:** When providing historical candlestick (K-line) lookback data to `KronosPredictor` or `KronosTokenizer`, **NEVER** slice from the head (`data[:512]`). Slicing the head feeds ancient data and drops recent candles.
- **Rule:** Always slice from the tail:
  ```python
  lookback_df = raw_df.iloc[-512:].copy()
  ```

---

## 3. Base Checkpoint Immutability
Pre-trained model checkpoints on Hugging Face (`NeoQuasar/Kronos-mini`, `NeoQuasar/Kronos-small`, `NeoQuasar/Kronos-base`, and `NeoQuasar/Kronos-Tokenizer-base`) are **strictly read-only**.
- Never overwrite or mutate base checkpoint weights.
- All experimental adaptations and fine-tuned checkpoints must be saved in `finetune/checkpoints/` or `candidates/`.

---

## 4. ASVL & The Rule-of-2 Circuit Breaker
Never assume code works. Never ask the user to manually test code. Always execute empirical CLI verification autonomously via ASVL:
- **Fast Smoke Check (<2s):** `python -m pytest tests/test_smoke.py -q` (run on every micro-step).
- **Full Suite Check:** `python -m pytest tests/ -q` (run only at final completion gate).
- **The Rule-of-2:** If the exact same test failure occurs **twice in a row**, you are strictly forbidden from attempting a third speculative edit. **HALT immediately**, output the exact terminal traceback, and escalate to the user.

---

## 5. Token & Context Bloat Hygiene (Zero Blackhole Credit Burning)
Tokens and API credits are real monetary assets. Prevent blackhole credit burning:
- **No File Re-reading:** Trust tool replacement diffs. Never re-read a file immediately after writing or editing it.
- **Cap Unbounded Output:** Pipe terminal logs through `Select-Object -First 25` or use `-q` in pytest. Keep command outputs under 25 lines.
- **Targeted Line Edits:** Always inspect line ranges before calling `replace_file_content`.
- **Graphify Code-Only:** Never run semantic graph passes on images (`figures/`) or papers. Use AST tree-sitter code analysis only.

---

## 6. Lessons Database Consultation
Before modifying architecture, financial logic, or PyTorch pipelines, consult the institutional guidance engine:
```bash
python scripts/lessons.py query --category coding --search "<keyword>"
```
Apply verified historical fixes before inventing new patterns.
