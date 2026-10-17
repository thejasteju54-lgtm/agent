"""Task Planner: Decomposes natural language requests into structured execution plans."""

import re
import uuid
from personal_ai.agent.task_models import ExecutionPlan, PlanStep, RiskLevel
from personal_ai.agent.permissions import PermissionPolicy
from personal_ai.tools.registry import ToolRegistry, default_registry
from personal_ai.models.base import BaseModelProvider
from personal_ai.logging.setup import get_logger

logger = get_logger(__name__)


class TaskPlanner:
    """Decomposes natural language tasks into validated execution plans."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        permission_policy: Optional[PermissionPolicy] = None,
        model_provider: Optional[BaseModelProvider] = None,
    ):
        self.registry = registry or default_registry
        self.permission_policy = permission_policy or PermissionPolicy()
        self.model_provider = model_provider

    def plan(
        self,
        prompt: str,
        task_id: Optional[str] = None,
        use_ai: bool = False,
    ) -> ExecutionPlan:
        """Create a structured execution plan for a prompt."""
        t_id = task_id or str(uuid.uuid4())
        clean_prompt = prompt.strip()

        # If AI planning requested and provider is configured
        if use_ai and self.model_provider:
            try:
                logger.info("Decomposing task with AI model provider (%s)...", self.model_provider.provider_name)
                ai_plan = self.model_provider.generate_plan(clean_prompt, self.registry.list_tools())
                ai_plan.task_id = t_id
                ai_plan.prompt = clean_prompt
                # Validate approval requirements according to active policy
                for step in ai_plan.steps:
                    step.requires_approval = self.permission_policy.requires_approval(step.risk_level)
                return ai_plan
            except Exception as e:
                logger.warning("AI model planning encountered an error: %s. Using deterministic planner.", e)

        # Check for empty or vague prompts requiring clarification
        if not clean_prompt or len(clean_prompt) < 3:
            return ExecutionPlan(
                task_id=t_id,
                prompt=clean_prompt,
                requires_clarification=True,
                clarification_question="The task description is empty or too brief. Please specify what you would like to automate.",
            )

        steps: List[PlanStep] = []
        assumptions: List[str] = []

        lower = clean_prompt.lower()

        # Deterministic pattern decomposition
        # 1. Browser navigation, screenshot, and web extraction
        url_match = re.search(r"((?:https?|file)://[^\s'\"]+)", clean_prompt)
        if url_match or "browse" in lower or "open url" in lower or "screenshot" in lower or "website" in lower:
            target_url = url_match.group(1) if url_match else "https://example.com"
            step_num = 1

            # Step: Open URL
            steps.append(
                PlanStep(
                    step_id=str(uuid.uuid4()),
                    step_number=step_num,
                    tool_name="browser_open_url",
                    description=f"Open URL '{target_url}'",
                    input_params={"url": target_url},
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    expected_outcome=f"Page at {target_url} loaded successfully",
                )
            )
            step_num += 1

            # Optional: Screenshot
            if "screenshot" in lower or "capture" in lower:
                steps.append(
                    PlanStep(
                        step_id=str(uuid.uuid4()),
                        step_number=step_num,
                        tool_name="browser_screenshot",
                        description=f"Capture screenshot of {target_url}",
                        input_params={"task_id": t_id, "file_name": f"screenshot_{t_id[:8]}.png"},
                        risk_level=RiskLevel.LOW,
                        requires_approval=False,
                        expected_outcome="Screenshot image saved to artifacts",
                    )
                )
                step_num += 1

            # Optional: Extract content
            if "extract" in lower or "content" in lower or "summary" in lower or "read" in lower:
                steps.append(
                    PlanStep(
                        step_id=str(uuid.uuid4()),
                        step_number=step_num,
                        tool_name="browser_extract_content",
                        description=f"Extract text content from {target_url}",
                        input_params={"selector": "body", "max_chars": 5000},
                        risk_level=RiskLevel.LOW,
                        requires_approval=False,
                        expected_outcome="Page text content extracted",
                    )
                )
                step_num += 1

        # 2. Deletion / Cleanup tasks
        elif "delete" in lower or "remove file" in lower:
            # Extract path if quoted or specified
            match = re.search(r"['\"]([^'\"]+)['\"]", clean_prompt)
            target_path = match.group(1) if match else clean_prompt.split()[-1]
            step = PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="delete_file",
                description=f"Delete file at '{target_path}'",
                input_params={"path": target_path},
                risk_level=RiskLevel.HIGH,
                requires_approval=self.permission_policy.requires_approval(RiskLevel.HIGH),
                expected_outcome=f"File {target_path} is deleted",
            )
            steps.append(step)

        # 2. File write / save note tasks
        elif "write" in lower or "save" in lower or "create file" in lower:
            # Match quoted path first
            quoted_match = re.search(r"to (?:file )?['\"]([^'\"]+)['\"]", clean_prompt)
            if quoted_match:
                target_path = quoted_match.group(1)
            else:
                unquoted_match = re.search(r"to (?:file )?([^\s'\"]+)", clean_prompt)
                target_path = unquoted_match.group(1) if unquoted_match else "output.txt"
            assumptions.append(f"Target file output path assumed as '{target_path}'.")

            # Extract content if specified, or generate summary placeholder
            content_match = re.search(r"content:?\s*['\"]([^'\"]+)['\"]", clean_prompt)
            content = content_match.group(1) if content_match else f"Automated output for task: {clean_prompt}"

            step = PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="write_file",
                description=f"Write content to '{target_path}'",
                input_params={"path": target_path, "content": content, "overwrite": True},
                risk_level=RiskLevel.MEDIUM,
                requires_approval=self.permission_policy.requires_approval(RiskLevel.MEDIUM),
                expected_outcome=f"File {target_path} exists and contains written content",
            )
            steps.append(step)

        # 3. Read file tasks
        elif "read" in lower or "view" in lower or "cat " in lower:
            match = re.search(r"['\"]([^'\"]+)['\"]", clean_prompt)
            target_path = match.group(1) if match else clean_prompt.split()[-1]

            step = PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="read_file",
                description=f"Read file content from '{target_path}'",
                input_params={"path": target_path},
                risk_level=RiskLevel.LOW,
                requires_approval=self.permission_policy.requires_approval(RiskLevel.LOW),
                expected_outcome=f"File {target_path} content retrieved",
            )
            steps.append(step)

        # 4. Directory list tasks
        elif "list" in lower or "directory" in lower or "folder" in lower:
            match = re.search(r"['\"]([^'\"]+)['\"]", clean_prompt)
            target_path = match.group(1) if match else "."

            step = PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="list_directory",
                description=f"List entries in directory '{target_path}'",
                input_params={"path": target_path},
                risk_level=RiskLevel.LOW,
                requires_approval=self.permission_policy.requires_approval(RiskLevel.LOW),
                expected_outcome="Directory contents listed",
            )
            steps.append(step)

        # Fallback generic plan
        else:
            assumptions.append("Interpreted as informational query.")
            step = PlanStep(
                step_id=str(uuid.uuid4()),
                step_number=1,
                tool_name="list_directory",
                description="List current workspace directory to inspect available resources",
                input_params={"path": "."},
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                expected_outcome="Directory listing obtained",
            )
            steps.append(step)

        return ExecutionPlan(
            task_id=t_id,
            prompt=clean_prompt,
            steps=steps,
            assumptions=assumptions,
            requires_clarification=False,
        )
