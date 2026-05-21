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


class CreateSessionResponse(BaseModel):
    sessionId: str
    model: str
    modelId: str | None = None
    reasoningEffort: str | None = None
    mode: str
    agentType: str = "coding"
    phase: str = "idle"
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


class SessionContextResponse(BaseModel):
    sessionId: str
    workspace: str
    mode: str
    model: str
    reasoningEffort: str | None = None
    agentType: str = "coding"
    phase: str = "idle"
    deployState: dict[str, Any] = Field(default_factory=dict)
    planState: dict[str, Any] = Field(default_factory=dict)
    selectedFilePath: str | None
    openFiles: list[str]
    messageCount: int
    toolCallCount: int
    thoughtCount: int
    estimatedTokens: int
    maxTokens: int
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
    model: str | None = None
    env_file: str | None = None
    reasoning_effort: str | None = None
    agent_type: str | None = None


class UIModelProviderPayload(BaseModel):
    id: str | None = None
    name: str
    baseUrl: str
    apiKey: str
    models: list[str] = Field(default_factory=list)
    provider: str | None = None


class ModelConfigPayload(BaseModel):
    providers: list[UIModelProviderPayload] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    autoApprove: bool = False


class SessionHistoryItem(BaseModel):
    sessionId: str
    workspace: str
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


class ChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    message: str
    agent_mode: str | None = None
    skills: list[str] = Field(default_factory=list)


class ContinueChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    assistant_id: str = Field(alias="assistant_id")


class TerminalInputRequest(BaseModel):
    command: str = ""
    submit: bool = True


class TerminalControlRequest(BaseModel):
    action: Literal["interrupt"]


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
