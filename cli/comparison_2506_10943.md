# 📊 Report Comparison: `products_2506_10943.md` (SEAL Paper)

I compared the report generated on the `main` branch vs the `dev` branch for paper 2506.10943 ("Self-Adapting Language Models").

## 🔍 Key Findings

| Attribute | `main` Branch (Old) | `dev` Branch (New) |
| :--- | :--- | :--- |
| **Top Idea #1** | **REACTIV MATERIALS** | **ModelGuard Enterprise** |
| **Domain** | Sci-Fi / Deep Tech (Molecular reconfiguration) | Enterprise Software (AI Governance) |
| **Hallucination Level** | **Extremely High**. Jumps from LLM weights to programmable matter. | **Low**. Stays within the AI/software domain. |
| **Verdict Accuracy** | **Poor**. Gave 92/100 to an impractical idea. | **Moderate**. More realistic but still over-optimistic (87/100). |
| **Idea Saturation** | Low (Random sci-fi ideas). | **High**. Logical but "standard" software ideas. |

## 🛠️ Root Cause Analysis: Prompt Differences

The change in output quality and style is directly linked to the persona shifts in `cli/paper2product/prompts.py`:

1.  **Persona Shift**:
    - `main`: "Ruthless market analyst"
    - `dev`: "Ruthless analyst... Think like a top-tier partner at Founders Fund or Sequoia."
2.  **Instruction Changes**:
    - `dev` explicitly instructs to "Think beyond software" and include "Deep tech (hardware, instruments, materials, biotech)".
    - Ironically, this extra structure seems to have **grounded** the model. In `main`, it was told to "Skip obvious matches" and be "Absurd", but without the "Company Builder" grounding, it just wrote sci-fi.
3.  **Pipeline Integrity**:
    - In `main`, the synthesizer hallucinated #1 (REACTIV MATERIALS) out of thin air—it wasn't even in the Red Team's list of candidates.
    - In `dev`, the synthesizer used ideas that actually appeared in the candidates, even if it ignored the Red Team's "❌" verdict.

## 💀 Red Team Results

Interestingly, the **Red Team** in the `dev` branch was significantly more brutal, failing EVERY idea (#1 through #5) with the conclusion that "academic AI advances rarely translate to standalone businesses."

### Survivors (According to Synthesizer)
- `main`: Reactiv Materials (92/100), Nexus Semiconductor (88/100), Memoria (85/100).
- `dev`: ModelGuard Enterprise (87/100), AdaptationOps (82/100), PersonalAI (79/100).

---

> [!IMPORTANT]
> The `dev` branch is much safer from a hallucination perspective, but as you noted, the ideas feel "saturated" because they are the most logical/safe software-first extensions of the paper.
