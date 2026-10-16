---
name: Autonomous Self-Verification Loop Skill (ASVL) - Kronos Quant Edition
description: Autonomous end-to-end self-verification loop skill for goal-based task execution, automated testing, continuous evaluation, and definitive completion gates with Rule-of-2 circuit breakers.
---

# Autonomous Self-Verification Loop Skill (ASVL) - Kronos Quant Edition

## 1. Goal-Oriented Execution & Codeflow Integration
ASVL is the execution and verification engine in Google Antigravity. It takes the **Granular Task Contract** from **Agent Codeflow** and anchors it into a structured, goal-based execution run:
- **Goal**: A clear, high-level description of the ultimate outcome.
- **Success Criteria**: A checklist of 3–5 specific, quantifiable, and testable outcomes required to satisfy the goal.
- **File Boundaries**: Strictly enforced from Codeflow's **File Boundary Matrix** (zero edits in the Forbidden Zone).
- **Step-by-Step Micro-Execution**: Execute atomic steps sequentially (Step 1 Schemas/Types -> Step 2 Quant Logic -> Step 3 Verification) rather than attempting a monolithic unverified overhaul.

---

## 2. Self-Verification & Testing Harness
Before declaring any code complete, configure and run automated verification tools autonomously. Do not rely on human review.
- **Fast Smoke Check (< 2s)**: `python -m pytest tests/test_smoke.py -q`
  - Runs on every micro-step.
  - Verifies $(B, T, D)$ tensor dimensions, tail-slicing logic, and Decimal conversions.
- **Full Backend Suite**: `python -m pytest tests/ -q` (executed at final completion gate).
- **Zero Float Math Invariant**: Verify all balances, limits, and PnL metrics use `decimal.Decimal`.
- **Lessons Guidance Loop**:
  - Before writing code, run `python scripts/lessons.py query --category <cat> --search "<kw>"`.
  - After fixing a non-trivial bug, stage the lesson via `python scripts/lessons.py stage ...`.

---

## 3. The Rule-of-2 Circuit Breaker (Anti-Blackhole Shield)
To prevent infinite retry spirals and runaway token consumption:
- If a terminal command or test fails, isolate the root cause, adjust code, and re-test.
- **THE RULE OF 2:** If the exact same test failure or error occurs **twice consecutively**, you are strictly forbidden from making a 3rd speculative edit.
- **Immediate Escalation:** Halt immediately, output the clean error stack, and yield control to the user.

---

## 4. Definitive Completion Gates
Exit the autonomous loop and return control to the user ONLY when ALL completion conditions are met:

### Complete When:
- [ ] All success criteria from the goal are met and verified.
- [ ] Changes respect the File Boundary Matrix (zero unintended diffs in the Forbidden Zone).
- [ ] You have actively executed and verified the work yourself (`python -m pytest tests/test_smoke.py -q` passes with exit code 0).
- [ ] Base model checkpoints remain pristine and untouched.
- [ ] Code is clean, documented, and invariant-compliant.

### Not Complete If:
- [ ] You assume or guess it works without running tests.
- [ ] Outstanding `TODO`s or placeholder mocks remain in production paths.
- [ ] You ask the user to manually verify or test the code.
