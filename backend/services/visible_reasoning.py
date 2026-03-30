import json
from typing import Dict, Any, List
from backend.core.logging import get_logger

logger = get_logger(__name__)

class VisibleReasoningService:
    """
    Generates UI-friendly reasoning from run artifacts.
    Strictly deterministic: Input JSON -> Output JSON/Text.
    """

    def generate_thinking(self, artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Produce 'Thinking' view content.
        artifacts: map of step_name -> artifact_json
        """
        steps = []
        final_rationale = []
        
        # 1. Plan / Strategy
        if "plan" in artifacts:
             steps.append({
                 "step_name": "Plan",
                 "text": "Strategy selected based on current market regime.",
                 "evidence_ids": []
             })
        
        # 2. News/Research
        if "news" in artifacts:
            news_brief = artifacts["news"]
            total_items = sum(len(a["clusters"]) for a in news_brief.get("assets", []))
            
            steps.append({
                "step_name": "Research",
                "text": f"Analyzed {total_items} news clusters for target assets.",
                "evidence_ids": [ev["item_id"] for a in news_brief.get("assets", []) for c in a["clusters"] for ev in c["items"]]
            })

            # Check for blockers
            if news_brief.get("blockers"):
                for blocker in news_brief["blockers"]:
                    steps.append({
                        "step_name": "Risk Check",
                        "text": f"BLOCKED {blocker['symbol']}: {blocker['reason']} (Severity: {blocker['severity']})",
                        "evidence_ids": blocker.get("evidence_item_ids", [])
                    })

        # 3. Decision
        if "decision" in artifacts:
            decision = artifacts["decision"]
            selected = decision.get("selected_asset")
            if selected:
                final_rationale.append({
                    "text": f"Selected {selected} for trading.",
                    "evidence_ids": decision.get("evidence_item_ids", [])
                })
                
                for constraint in decision.get("constraints_triggered", []):
                    final_rationale.append({
                        "text": f"Constraint Triggered: {constraint['name']} ({constraint['severity']})",
                        "evidence_ids": constraint.get("evidence_ids", [])
                    })
            else:
                final_rationale.append({
                    "text": "No asset selected. Strategy output was neutral or blocked.",
                    "evidence_ids": []
                })

        return {
            "headline": "Run Analysis completed.",
            "narrative_steps": steps,
            "final_rationale_bullets": final_rationale
        }
