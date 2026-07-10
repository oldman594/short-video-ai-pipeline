from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.config import OUTPUT_DIR
from app.providers import (
    DeepSeekAnalysisProvider,
    DIDAvatarVideoProvider,
    ExternalHttpAvatarVideoProvider,
    MockAvatarVideoProvider,
    MockLLMProvider,
    SourceInput,
    default_avatar_video_provider,
    default_llm_provider,
)
from app.storage import Repository
from app.text_extraction import TextExtractionRouter


class WorkflowService:
    def __init__(
        self,
        repository: Repository,
        text_extractor: TextExtractionRouter | None = None,
        llm_provider: MockLLMProvider | DeepSeekAnalysisProvider | None = None,
        avatar_provider: MockAvatarVideoProvider | ExternalHttpAvatarVideoProvider | DIDAvatarVideoProvider | None = None,
    ):
        self.repository = repository
        self.text_extractor = text_extractor or TextExtractionRouter()
        self.llm_provider = llm_provider or default_llm_provider()
        self.avatar_provider = avatar_provider or default_avatar_video_provider()

    def process_project(self, project_id: str) -> None:
        project = self.repository.get_project(project_id)
        if project is None:
            return
        try:
            self.repository.update_project_status(project_id, "processing")
            source = SourceInput(
                source_type=project["source_type"],
                title=project["title"],
                platform=project["platform"],
                source_url=project["source_url"],
                source_file_path=project["source_file_path"],
                notes=project["notes"],
            )
            transcript = self.text_extractor.extract(
                source,
                preference=project["extraction_preference"],
            )
            self.repository.save_transcript(project_id, transcript)

            analysis = self.llm_provider.analyze(
                transcript["raw_text"],
                title=project["title"],
                platform=project["platform"],
            )
            self.repository.save_analysis(project_id, analysis)

            scripts = self.llm_provider.generate_scripts(
                transcript["raw_text"],
                analysis=analysis,
                title=project["title"],
                target_topic=project.get("target_topic") or project["title"],
                target_notes=project["notes"],
            )
            self.repository.replace_scripts(project_id, scripts)
            self.repository.update_project_status(project_id, "ready_for_review")
        except Exception as exc:
            self.repository.update_project_status(project_id, "failed", str(exc))

    def render_script(self, script_id: str, render_job_id: str) -> None:
        script = self.repository.get_script(script_id)
        if script is None:
            self.repository.update_render_job(render_job_id, "failed", error_message="script not found")
            return
        if script["status"] != "approved":
            self.repository.update_render_job(
                render_job_id,
                "failed",
                error_message="script must be approved before rendering",
            )
            return
        try:
            self.repository.update_render_job(render_job_id, "running")
            result = self.avatar_provider.render(
                OUTPUT_DIR,
                script_id=script_id,
                script_text=script["script_text"],
                title_options=script["title_options"],
            )
            self.repository.update_render_job(
                render_job_id,
                "succeeded",
                output_video_url=result["output_video_url"],
            )
        except Exception as exc:
            self.repository.update_render_job(render_job_id, "failed", error_message=str(exc))


class BackgroundRunner:
    def __init__(self, workflow: WorkflowService):
        self.workflow = workflow
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mvp-worker")

    def enqueue_project(self, project_id: str) -> None:
        self.executor.submit(self.workflow.process_project, project_id)

    def enqueue_render(self, script_id: str, render_job_id: str) -> None:
        self.executor.submit(self.workflow.render_script, script_id, render_job_id)
