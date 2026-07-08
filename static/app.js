const state = {
  projects: [],
  activeProjectId: null,
  activeProject: null,
  activeScriptId: null,
  pollTimer: null,
};

const els = {
  form: document.querySelector("#project-form"),
  sourceType: document.querySelector("#source-type"),
  linkField: document.querySelector("#link-field"),
  uploadField: document.querySelector("#upload-field"),
  uploadLabel: document.querySelector("#upload-label"),
  uploadHelp: document.querySelector("#upload-help"),
  refreshTools: document.querySelector("#refresh-tools"),
  toolStatus: document.querySelector("#tool-status"),
  refreshProjects: document.querySelector("#refresh-projects"),
  projectList: document.querySelector("#project-list"),
  emptyState: document.querySelector("#empty-state"),
  detail: document.querySelector("#project-detail"),
  projectPlatform: document.querySelector("#project-platform"),
  projectTitle: document.querySelector("#project-title"),
  projectMeta: document.querySelector("#project-meta"),
  projectStatus: document.querySelector("#project-status"),
  projectError: document.querySelector("#project-error"),
  extractionInfo: document.querySelector("#extraction-info"),
  transcriptText: document.querySelector("#transcript-text"),
  saveTranscript: document.querySelector("#save-transcript"),
  analysisView: document.querySelector("#analysis-view"),
  scriptTabs: document.querySelector("#script-tabs"),
  scriptEditor: document.querySelector("#script-editor"),
  saveScript: document.querySelector("#save-script"),
  approveScript: document.querySelector("#approve-script"),
  renderScript: document.querySelector("#render-script"),
  publishCopy: document.querySelector("#publish-copy"),
  renderJobs: document.querySelector("#render-jobs"),
  toast: document.querySelector("#toast"),
};

function api(path, options = {}) {
  return fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `请求失败：${response.status}`);
    }
    return payload;
  });
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  window.setTimeout(() => els.toast.classList.add("hidden"), 2600);
}

function statusLabel(status) {
  const labels = {
    queued: "排队中",
    processing: "处理中",
    ready_for_review: "待审核",
    failed: "失败",
  };
  return labels[status] || status || "未知";
}

function renderProjectList() {
  if (!state.projects.length) {
    els.projectList.innerHTML = '<p class="muted">暂无项目</p>';
    return;
  }
  els.projectList.innerHTML = "";
  state.projects.forEach((project) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `project-item ${project.id === state.activeProjectId ? "active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(project.title)}</strong>
      <span>${escapeHtml(project.platform || "unknown")} · ${statusLabel(project.status)}</span>
      <span>${escapeHtml(project.created_at)}</span>
    `;
    button.addEventListener("click", () => selectProject(project.id));
    els.projectList.appendChild(button);
  });
}

async function loadProjects() {
  const payload = await api("/api/projects");
  state.projects = payload.projects || [];
  renderProjectList();
}

async function loadToolStatus() {
  const payload = await api("/api/system/text-extraction-tools");
  els.toolStatus.innerHTML = (payload.tools || [])
    .map((tool) => {
      const state = tool.available ? "可用" : "缺失";
      const className = tool.available ? "ok" : "missing";
      return `
        <div class="tool-row">
          <div>
            <strong>${escapeHtml(tool.name)}</strong>
            <p>${escapeHtml(tool.purpose)}</p>
            ${tool.available ? `<p>${escapeHtml(tool.path)}</p>` : `<p>${escapeHtml(tool.install_hint)}</p>`}
          </div>
          <span class="${className}">${state}</span>
        </div>
      `;
    })
    .join("");
}

async function selectProject(projectId) {
  state.activeProjectId = projectId;
  state.activeProject = await api(`/api/projects/${projectId}`);
  if (!state.activeScriptId || !state.activeProject.scripts.some((script) => script.id === state.activeScriptId)) {
    state.activeScriptId = state.activeProject.scripts[0]?.id || null;
  }
  renderProjectList();
  renderDetail();
  schedulePolling();
}

function renderDetail() {
  const project = state.activeProject;
  if (!project) {
    els.emptyState.classList.remove("hidden");
    els.detail.classList.add("hidden");
    return;
  }

  els.emptyState.classList.add("hidden");
  els.detail.classList.remove("hidden");
  els.projectPlatform.textContent = project.platform || "unknown";
  els.projectTitle.textContent = project.title;
  els.projectMeta.textContent = `${project.source_type === "upload" ? "上传视频" : "视频链接"} · ${extractionLabel(project.extraction_preference)} · ${project.updated_at}`;
  els.projectStatus.textContent = statusLabel(project.status);

  if (project.error_message) {
    els.projectError.textContent = project.error_message;
    els.projectError.classList.remove("hidden");
  } else {
    els.projectError.classList.add("hidden");
  }

  renderExtractionInfo(project.transcript);

  els.transcriptText.value = project.transcript?.raw_text || "";
  renderAnalysis(project.analysis);
  renderScripts(project.scripts || []);
  renderPublishCopy(activeScript());
  renderJobs(project.render_jobs || []);
}

function renderAnalysis(analysis) {
  if (!analysis) {
    els.analysisView.innerHTML = '<p class="muted">等待分析任务完成。</p>';
    return;
  }
  els.analysisView.innerHTML = `
    ${analysisBlock("主题", analysis.topic)}
    ${analysisBlock("目标受众", analysis.audience)}
    ${analysisBlock("开头钩子", analysis.hook)}
    ${listBlock("结构", analysis.structure?.map((item) => `${item.step}: ${item.summary}`) || [])}
    ${listBlock("可借鉴点", analysis.key_points || [])}
    ${listBlock("风险提示", analysis.risks || [])}
  `;
}

function renderExtractionInfo(transcript) {
  if (!transcript) {
    els.extractionInfo.classList.add("hidden");
    return;
  }
  const warnings = transcript.warnings || [];
  const warningText = warnings.length ? ` 提示：${warnings.join("；")}` : "";
  const subtitleLink = transcript.subtitle_file_url
    ? ` <a href="${transcript.subtitle_file_url}" target="_blank" rel="noreferrer">下载字幕文件</a>`
    : "";
  els.extractionInfo.innerHTML = `${escapeHtml(`文本提取：${extractionLabel(transcript.extraction_method)} · ${transcript.asr_provider}.${warningText}`)}${subtitleLink}`;
  els.extractionInfo.classList.toggle("warning", warnings.length > 0);
  els.extractionInfo.classList.remove("hidden");
}

function extractionLabel(value) {
  const labels = {
    auto: "自动判断",
    subtitle_track: "字幕轨",
    speech: "语音识别",
    screen_text: "画面文字 OCR",
    network_captions: "网络字幕",
    auto_combined: "自动合并",
  };
  return labels[value] || value || "未知";
}

function renderScripts(scripts) {
  els.scriptTabs.innerHTML = "";
  if (!scripts.length) {
    els.scriptEditor.value = "";
    els.scriptEditor.placeholder = "等待脚本生成。";
    disableScriptActions(true);
    return;
  }
  disableScriptActions(false);
  scripts.forEach((script) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tab ${script.id === state.activeScriptId ? "active" : ""}`;
    button.textContent = `版本 ${script.version}${script.status === "approved" ? " · 已批准" : ""}`;
    button.addEventListener("click", () => {
      state.activeScriptId = script.id;
      renderDetail();
    });
    els.scriptTabs.appendChild(button);
  });
  const script = activeScript();
  els.scriptEditor.value = script?.script_text || "";
}

function renderPublishCopy(script) {
  if (!script) {
    els.publishCopy.innerHTML = '<p class="muted">批准脚本后可复制发布文案。</p>';
    return;
  }
  const title = script.title_options?.[0] || state.activeProject.title;
  const cover = script.cover_text_options?.[0] || "原创改写";
  const tags = (script.tags || []).map((tag) => `#${tag}`).join(" ");
  els.publishCopy.innerHTML = `
    <div class="copy-block">
      <h4>标题</h4>
      <p>${escapeHtml(title)}</p>
    </div>
    <div class="copy-block">
      <h4>封面文案</h4>
      <p>${escapeHtml(cover)}</p>
    </div>
    <div class="copy-block">
      <h4>简介</h4>
      <p>${escapeHtml("基于参考内容结构重新创作，发布前已人工审核。")}</p>
    </div>
    <div class="copy-block">
      <h4>标签</h4>
      <p>${escapeHtml(tags)}</p>
    </div>
  `;
}

function renderJobs(jobs) {
  if (!jobs.length) {
    els.renderJobs.innerHTML = '<p class="muted">暂无渲染任务。</p>';
    return;
  }
  els.renderJobs.innerHTML = jobs
    .map((job) => {
      const link = job.output_video_url
        ? `<p><a href="${job.output_video_url}" target="_blank" rel="noreferrer">下载草稿文件</a></p>`
        : "";
      const error = job.error_message ? `<p>错误：${escapeHtml(job.error_message)}</p>` : "";
      return `
        <div class="job-block">
          <h4>${escapeHtml(job.status)} · ${escapeHtml(job.provider)}</h4>
          <p>${escapeHtml(job.updated_at)}</p>
          ${link}
          ${error}
        </div>
      `;
    })
    .join("");
}

function analysisBlock(title, value) {
  return `
    <div class="analysis-block">
      <h4>${escapeHtml(title)}</h4>
      <p>${escapeHtml(value || "暂无")}</p>
    </div>
  `;
}

function listBlock(title, values) {
  const items = values.length ? values.map((value) => `<li>${escapeHtml(value)}</li>`).join("") : "<li>暂无</li>";
  return `
    <div class="analysis-block">
      <h4>${escapeHtml(title)}</h4>
      <ul>${items}</ul>
    </div>
  `;
}

function activeScript() {
  return state.activeProject?.scripts?.find((script) => script.id === state.activeScriptId) || null;
}

function disableScriptActions(disabled) {
  els.saveScript.disabled = disabled;
  els.approveScript.disabled = disabled;
  els.renderScript.disabled = disabled;
}

function schedulePolling() {
  window.clearInterval(state.pollTimer);
  state.pollTimer = window.setInterval(async () => {
    if (!state.activeProjectId) {
      return;
    }
    const project = await api(`/api/projects/${state.activeProjectId}`);
    state.activeProject = project;
    renderDetail();
    await loadProjects();
    const hasRunningWork =
      project.status === "queued" ||
      project.status === "processing" ||
      (project.render_jobs || []).some((job) => job.status === "queued" || job.status === "running");
    if (!hasRunningWork) {
      window.clearInterval(state.pollTimer);
    }
  }, 1500);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.sourceType.addEventListener("change", () => {
  const isUpload = els.sourceType.value === "upload";
  els.linkField.classList.toggle("hidden", isUpload);
  els.uploadLabel.textContent = isUpload ? "视频文件（必选）" : "已下载视频文件（可选）";
  els.uploadHelp.textContent = isUpload
    ? "服务端会对这个文件执行字幕轨、语音识别或 OCR 提取。"
    : "链接会记录来源；如果平台链接无法直接提取，请附带你本地保存的视频文件，由服务端提取文本。";
});

els.refreshTools.addEventListener("click", async () => {
  await loadToolStatus();
  showToast("服务端工具状态已刷新");
});

els.refreshProjects.addEventListener("click", async () => {
  await loadProjects();
  showToast("项目列表已刷新");
});

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(els.form);
  const sourceType = formData.get("source_type");
  const payload = {
    source_type: sourceType,
    title: formData.get("title"),
    platform: formData.get("platform"),
    source_url: formData.get("source_url"),
    notes: formData.get("notes"),
    extraction_preference: formData.get("extraction_preference"),
  };
  const file = formData.get("file");
  if (file && file.name) {
    payload.file = {
      filename: file.name,
      content_base64: await readFileAsDataUrl(file),
    };
  } else if (sourceType === "upload") {
      showToast("请选择要上传的文件");
      return;
  }
  const project = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  els.form.reset();
  els.sourceType.dispatchEvent(new Event("change"));
  await loadProjects();
  await selectProject(project.id);
  showToast("项目已创建，后台正在处理");
});

els.saveTranscript.addEventListener("click", async () => {
  if (!state.activeProjectId) return;
  await api(`/api/projects/${state.activeProjectId}/transcript`, {
    method: "PATCH",
    body: JSON.stringify({ raw_text: els.transcriptText.value }),
  });
  await selectProject(state.activeProjectId);
  showToast("转写文本已保存");
});

els.saveScript.addEventListener("click", async () => {
  const script = activeScript();
  if (!script) return;
  await api(`/api/scripts/${script.id}`, {
    method: "PATCH",
    body: JSON.stringify({ script_text: els.scriptEditor.value }),
  });
  await selectProject(state.activeProjectId);
  showToast("脚本已保存");
});

els.approveScript.addEventListener("click", async () => {
  const script = activeScript();
  if (!script) return;
  const updated = await api(`/api/scripts/${script.id}/approve`, { method: "POST" });
  state.activeScriptId = updated.id;
  await selectProject(state.activeProjectId);
  showToast("脚本已批准");
});

els.renderScript.addEventListener("click", async () => {
  const script = activeScript();
  if (!script) return;
  await api(`/api/scripts/${script.id}/render`, { method: "POST" });
  await selectProject(state.activeProjectId);
  showToast("渲染任务已创建");
});

els.sourceType.dispatchEvent(new Event("change"));
loadProjects().catch((error) => showToast(error.message));
loadToolStatus().catch((error) => showToast(error.message));
