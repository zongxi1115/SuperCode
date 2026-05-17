from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateSessionResponse(BaseModel):
    sessionId: str
    model: str
    modelId: str | None = None
    mode: str
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
    planSteps: list[dict[str, str]]


class CreateSessionRequest(BaseModel):
    workspace: str | None = None
    model: str | None = None
    env_file: str | None = None


class UIModelProviderPayload(BaseModel):
    id: str | None = None
    name: str
    baseUrl: str
    apiKey: str
    models: list[str] = Field(default_factory=list)
    provider: str | None = None


class ModelConfigPayload(BaseModel):
    providers: list[UIModelProviderPayload] = Field(default_factory=list)


class SessionHistoryItem(BaseModel):
    sessionId: str
    workspace: str
    mode: str
    model: str
    title: str
    preview: str
    messageCount: int
    toolCallCount: int
    createdAt: int
    updatedAt: int


class ChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    message: str


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


class GitCommitRequest(BaseModel):
    message: str


class GitTagRequest(BaseModel):
    tag: str
    message: str | None = None
