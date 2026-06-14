from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CodeChangeRecord(BaseModel):
    id: str
    action: Literal["added", "modified", "deleted"]
    path: str
    absolutePath: str | None = None
    source: str = "agent"
    toolCallId: str | None = None
    assistantId: str | None = None
    turnIndex: int | None = None
    stepIndex: int | None = None
    timestamp: int
    linesAdded: int = 0
    linesDeleted: int = 0
    summary: str
    diffPreview: str = ""


class SkillSummary(BaseModel):
    id: str
    name: str
    description: str
    scope: str
    sourcePath: str | None = None


class PluginSummary(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    navSlot: str
    enabled: bool = True
    loadable: bool = False
    loaded: bool = False


class CreateSessionResponse(BaseModel):
    sessionId: str
    model: str
    modelId: str | None = None
    reasoningEffort: str | None = None
    mode: str
    executionMode: Literal["local", "worktree"] = "local"
    baseWorkspace: str | None = None
    worktreePath: str | None = None
    worktreeBranch: str | None = None
    agentType: str = "coding"
    phase: str = "idle"
    routeState: dict[str, Any] = Field(default_factory=dict)
    deployState: dict[str, Any] = Field(default_factory=dict)
    planState: dict[str, Any] = Field(default_factory=dict)
    isGenerating: bool
    startupError: str | None
    envFile: str | None
    workspace: str
    workspaceOptions: list[dict[str, str]]
    messages: list[dict[str, Any]]
    toolCalls: list[dict[str, Any]]
    thoughts: list[str]
    terminalOutput: str
    previewUrl: str
    fileTree: list[dict[str, Any]]
    fileTreeRevision: int = 0
    selectedFilePath: str | None
    selectedFileContent: str
    openFiles: list[str]
    availableSkills: list[SkillSummary] = Field(default_factory=list)
    codeChanges: list[CodeChangeRecord] = Field(default_factory=list)
    planSteps: list[dict[str, str]]


class SessionContextMessage(BaseModel):
    role: str
    content: str


class SessionContextTool(BaseModel):
    id: str
    name: str
    state: str
    success: bool | None = None


class SessionTokenUsage(BaseModel):
    inputTokens: int = 0
    outputTokens: int = 0
    reasoningTokens: int = 0
    cachedInputTokens: int = 0
    totalTokens: int = 0


class SessionContextResponse(BaseModel):
    sessionId: str
    workspace: str
    mode: str
    executionMode: Literal["local", "worktree"] = "local"
    baseWorkspace: str | None = None
    worktreePath: str | None = None
    worktreeBranch: str | None = None
    model: str
    reasoningEffort: str | None = None
    agentType: str = "coding"
    phase: str = "idle"
    routeState: dict[str, Any] = Field(default_factory=dict)
    deployState: dict[str, Any] = Field(default_factory=dict)
    planState: dict[str, Any] = Field(default_factory=dict)
    selectedFilePath: str | None
    openFiles: list[str]
    messageCount: int
    toolCallCount: int
    thoughtCount: int
    estimatedTokens: int
    maxTokens: int
    usage: SessionTokenUsage = Field(default_factory=SessionTokenUsage)
    cumulativeUsage: SessionTokenUsage = Field(default_factory=SessionTokenUsage)
    recentMessages: list[SessionContextMessage]
    recentThoughts: list[str]
    recentTools: list[SessionContextTool]
    codeChangeCount: int = 0
    recentCodeChanges: list[CodeChangeRecord] = Field(default_factory=list)
    availableSkills: list[SkillSummary] = Field(default_factory=list)
    planSteps: list[dict[str, str]]


class SessionContextCompressionRequest(BaseModel):
    mode: Literal["preview", "apply"] = "preview"
    usageThreshold: float = 0.7
    preserveRecentMessages: int = 6
    preserveRecentTools: int = 8
    preserveRecentThoughts: int = 4
    instruction: str | None = None


class SessionContextCompressionResponse(BaseModel):
    sessionId: str
    mode: Literal["preview", "apply"]
    applied: bool
    summary: str
    usageRatio: float
    usageThreshold: float
    sourceMessageCount: int
    sourceToolCount: int
    sourceThoughtCount: int
    preservedMessageCount: int
    preservedToolCount: int
    preservedThoughtCount: int
    originalEstimatedTokens: int
    maxTokens: int
    compressedEstimatedTokens: int
    savedEstimatedTokens: int
    usedFallback: bool = False
    skippedReason: str | None = None
    updatedContext: SessionContextResponse | None = None


class SessionRestoreRequest(BaseModel):
    messageId: str


class CreateSessionRequest(BaseModel):
    workspace: str | None = None
    execution_mode: Literal["local", "worktree"] = "local"
    initialize_git_repository: bool = False
    model: str | None = None
    env_file: str | None = None
    reasoning_effort: str | None = None
    agent_type: str | None = None


class UIModelRecordPayload(BaseModel):
    id: str
    contextWindow: int | None = None


class UIModelProviderPayload(BaseModel):
    id: str | None = None
    name: str
    baseUrl: str
    apiKey: str
    models: list[UIModelRecordPayload] = Field(default_factory=list)
    provider: str | None = None
    apiMode: Literal["chat_completions", "responses"] | None = None


class ModelConfigPayload(BaseModel):
    providers: list[UIModelProviderPayload] = Field(default_factory=list)


class EmbeddingSettingsPayload(BaseModel):
    enabled: bool = False
    baseUrl: str = ""
    apiKey: str = ""
    model: str = ""


class MCPServerPayload(BaseModel):
    id: str | None = None
    name: str = ""
    enabled: bool = True
    transport: Literal["stdio", "streamable_http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    bearerToken: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class MCPServersPayload(BaseModel):
    servers: list[MCPServerPayload] = Field(default_factory=list)


class MCPServerTestRequest(BaseModel):
    server: MCPServerPayload | None = None


class ImageGenerationSettingsPayload(BaseModel):
    enabled: bool = False
    baseUrl: str = ""
    apiKey: str = ""
    model: str = ""
    size: str = "1024x1024"
    quality: str = "auto"


class MemoryItemPayload(BaseModel):
    id: str
    content: str
    scope: Literal["global", "workspace"] = "global"
    enabled: bool = True
    createdAt: int
    updatedAt: int
    sourceSessionId: str | None = None
    sourcePreview: str | None = None


class MemorySettingsPayload(BaseModel):
    enabled: bool = True
    autoLearn: bool = True
    global_: list[MemoryItemPayload] = Field(default_factory=list, alias="global")
    workspaces: dict[str, list[MemoryItemPayload]] = Field(default_factory=dict)


class SettingsPayload(BaseModel):
    autoApprove: bool = False
    thinkingRendering: Literal["text", "markdown"] = "text"
    finalAnswerRendering: Literal["markdown", "html"] = "markdown"
    bodyFontFamily: str = 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    bodyFontSize: int = 14
    bodyLineHeight: int = 22
    embedding: EmbeddingSettingsPayload = Field(default_factory=EmbeddingSettingsPayload)
    imageGeneration: ImageGenerationSettingsPayload = Field(default_factory=ImageGenerationSettingsPayload)
    memory: MemorySettingsPayload = Field(default_factory=MemorySettingsPayload)


class SessionHistoryItem(BaseModel):
    sessionId: str
    workspace: str
    executionMode: Literal["local", "worktree"] = "local"
    baseWorkspace: str | None = None
    worktreePath: str | None = None
    worktreeBranch: str | None = None
    mode: str
    model: str
    agentType: str = "coding"
    phase: str = "idle"
    title: str
    preview: str
    messageCount: int
    toolCallCount: int
    createdAt: int
    updatedAt: int


class ChatAttachmentPayload(BaseModel):
    id: str | None = None
    type: Literal["image", "file"] = "file"
    filename: str = ""
    mediaType: str = ""
    dataUrl: str


class ChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    message: str
    execution_mode: Literal["local", "worktree"] = "local"
    agent_mode: str | None = None
    super_autopilot: bool = False
    skills: list[str] = Field(default_factory=list)
    attachments: list[ChatAttachmentPayload] = Field(default_factory=list)


class ContinueChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    assistant_id: str = Field(alias="assistant_id")


class TerminalInputRequest(BaseModel):
    command: str = ""
    key: str | None = None
    submit: bool = True


class TerminalControlRequest(BaseModel):
    action: Literal["interrupt"]


class CreateTerminalRequest(BaseModel):
    cwd: str | None = None
    name: str | None = None


class TerminalInfoResponse(BaseModel):
    terminalId: str
    name: str
    shell: str
    backend: str
    cwd: str | None = None
    isAlive: bool = True
    isDefault: bool = False
    kind: Literal["interactive", "managed-process"] = "interactive"
    command: str | None = None
    rootPid: int | None = None
    status: str | None = None
    startedAt: int | None = None


class ToolConfirmationRequest(BaseModel):
    approved: bool


class ConnectToolSubmitRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class ToolInputAnswer(BaseModel):
    questionId: str
    selectedOptionIds: list[str] = Field(default_factory=list)
    otherText: str | None = None
    text: str | None = None


class ToolInputSubmitRequest(BaseModel):
    answers: list[ToolInputAnswer] = Field(default_factory=list)


class PlanSubmitRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    overview: str | None = None
    keySteps: list[str] = Field(default_factory=list)
    markdown: str | None = None


class PlanDraftUpdateRequest(BaseModel):
    title: str | None = None
    markdown: str


class TaskStepInput(BaseModel):
    title: str
    summary: str


class CreateTaskRequest(BaseModel):
    title: str
    summary: str
    steps: list[TaskStepInput] = Field(default_factory=list)


class FinishTaskRequest(BaseModel):
    step_id: str


class TerminalSnapshotResponse(BaseModel):
    sessionId: str
    output: str
    revision: int
    isAlive: bool
    shell: str
    backend: str = "subprocess"
    cwd: str | None = None
    supportsInterrupt: bool = False
    supportsRawInput: bool = True
    supportsResize: bool = False
    fileTree: list[dict[str, Any]] | None = None
    processes: list[dict[str, Any]] | None = None


class ManagedProcessInfo(BaseModel):
    pid: int
    parent_pid: int
    name: str
    command_line: str
    is_root: bool


class ManagedProcessResponse(BaseModel):
    terminalId: str
    command: str
    rootPid: int
    status: str
    returnCode: int | None
    startedAt: int
    terminatedAt: int | None
    processCount: int
    processes: list[ManagedProcessInfo]


class SwitchModelRequest(BaseModel):
    model: str | None = None
    env_file: str | None = None
    reasoning_effort: str | None = None


class GitCommitRequest(BaseModel):
    message: str


class GitTagRequest(BaseModel):
    tag: str
    message: str | None = None


class KanbanBoardCreateRequest(BaseModel):
    name: str = "默认看板"
    description: str | None = None


class KanbanCardCreateRequest(BaseModel):
    boardId: str
    title: str
    columnId: str | None = None
    status: str | None = None
    description: str | None = None
    priority: str = "none"
    labels: list[str] = Field(default_factory=list)
    assignee: str | None = None


class KanbanCardUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    labels: list[str] | None = None
    assignee: str | None = None
    columnId: str | None = None
    status: str | None = None
    position: float | None = None
    aiState: dict[str, Any] | None = None


class KanbanCardReorderRequest(BaseModel):
    boardId: str
    cardId: str | None = None
    columnId: str | None = None
    targetColumnId: str | None = None
    orderedCardIds: list[str] = Field(default_factory=list)
