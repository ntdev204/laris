"use client";

import {
  useEffect, useLayoutEffect, useRef, useState,
  type ChangeEvent, type DragEvent, type FormEvent, type KeyboardEvent,
} from "react";
import {
  BookOpen, Check, Copy, FileText, KeyRound, ListChecks, MessageSquare,
  MoreHorizontal, Paperclip, Pencil, Plus, Search, Send, Sparkles, Square, Trash2, X,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput, InputGroupTextarea,
} from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader,
  SidebarInset, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem,
  SidebarProvider, SidebarTrigger, useSidebar,
} from "@/components/ui/sidebar";
import {
  fileAccept, makeRequest, readAttachment, streamReply, type Attachment, type Chat, type Message,
} from "@/lib/chat";
import { readHistory, writeHistory } from "@/lib/history";

const emptyDraft = { text: "", files: [] as Attachment[], issue: "" };
const suggestions = [
  { icon: BookOpen, label: "Hiểu một chủ đề", text: "Giải thích một chủ đề khoa học bằng ví dụ đơn giản: " },
  { icon: ListChecks, label: "Lập kế hoạch", text: "Giúp mình lập kế hoạch tìm hiểu về: " },
  { icon: FileText, label: "Đọc tài liệu", text: "Tóm tắt tài liệu mình đính kèm và liệt kê các ý chính." },
];
type Draft = typeof emptyDraft;
type Modal = "key" | "rename" | "delete";
type LiveReply = { chatId: string; text: string };

export function ChatWorkspace({ maxRequestBytes }: { maxRequestBytes: number }) {
  return (
    <SidebarProvider className="h-dvh min-h-0 overflow-hidden">
      <Workspace maxRequestBytes={maxRequestBytes} />
    </SidebarProvider>
  );
}

function Workspace({ maxRequestBytes }: { maxRequestBytes: number }) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [storageIssue, setStorageIssue] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [issues, setIssues] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modal, setModal] = useState<{ kind: Modal; chat?: Chat } | null>(null);
  const [copiedId, setCopiedId] = useState("");
  const [dragging, setDragging] = useState(false);
  const [reading, setReading] = useState<string[]>([]);
  const [live, setLive] = useState<LiveReply | null>(null);
  const controller = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const prompt = useRef<HTMLTextAreaElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const dragDepth = useRef(0);
  const { isMobile, setOpenMobile } = useSidebar();

  const chat = chats.find(({ id }) => id === selectedId);
  const draftKey = selectedId ?? "";
  const draft = drafts[draftKey] ?? emptyDraft;
  const active = live?.chatId === selectedId;
  const issue = selectedId ? issues[selectedId] : "";
  const last = chat?.messages.at(-1);
  const matching = chats.filter(({ title }) => title.toLowerCase().includes(search.trim().toLowerCase()));
  const readingDraft = reading.includes(draftKey);

  useEffect(() => {
    let mounted = true;
    void readHistory().then(
      (saved) => { if (mounted) setChats(saved); },
      () => { if (mounted) setStorageIssue("Không đọc được lịch sử lưu trên trình duyệt."); },
    ).finally(() => { if (mounted) setLoaded(true); });
    return () => {
      mounted = false;
      controller.current?.abort();
    };
  }, []);

  function persist(item: Chat | string) {
    void writeHistory(item).catch(() => {
      setStorageIssue("Trình duyệt không lưu được thay đổi lịch sử. Chat vẫn mở trong tab này.");
    });
  }

  useLayoutEffect(() => {
    if (follow.current && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [chat, selectedId, live, issue]);

  function openChat(id: string | null) {
    follow.current = true;
    setSelectedId(id);
    if (isMobile) setOpenMobile(false);
  }

  function updateDraft(key: string, patch: Partial<Draft>) {
    setDrafts((current) => ({ ...current, [key]: { ...(current[key] ?? emptyDraft), ...patch } }));
  }

  async function addFiles(files: File[]) {
    if (!files.length || readingDraft) return;
    const existingBytes = new Blob(draft.files.map(({ text }) => text)).size;
    if (files.reduce((sum, file) => sum + file.size, existingBytes) > maxRequestBytes) {
      updateDraft(draftKey, { issue: "Các tệp vượt quá giới hạn dung lượng của máy chủ." });
      return;
    }
    setReading((current) => [...current, draftKey]);
    const results = await Promise.allSettled(files.map((file) => readAttachment(file, maxRequestBytes)));
    setDrafts((current) => {
      const previous = current[draftKey] ?? emptyDraft;
      const attachments = [...previous.files];
      const failures = new Set<string>();
      for (const result of results) {
        if (result.status === "fulfilled") attachments.push(result.value);
        else failures.add(result.reason instanceof TypeError ? "Tệp phải có mã hóa UTF-8." : result.reason.message);
      }
      return {
        ...current, [draftKey]: { ...previous, files: attachments, issue: [...failures].join(" ") },
      };
    });
    setReading((current) => current.filter((key) => key !== draftKey));
  }

  function chooseFiles(event: ChangeEvent<HTMLInputElement>) {
    void addFiles(Array.from(event.currentTarget.files ?? []));
    event.currentTarget.value = "";
  }

  function dropFiles(event: DragEvent) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    void addFiles(Array.from(event.dataTransfer.files));
  }

  async function run(next: Chat, requestBody: string) {
    const abort = new AbortController();
    controller.current = abort;
    setIssues((current) => ({ ...current, [next.id]: "" }));
    setLive({ chatId: next.id, text: "" });
    let text = "";
    let interrupted = false;
    try {
      const headers = new Headers({ "Content-Type": "application/json" });
      if (apiKey) headers.set("Authorization", `Bearer ${apiKey}`);
      const response = await fetch("/api/chat", {
        method: "POST", headers, body: requestBody, signal: abort.signal,
      });
      await streamReply(response, (delta) => {
        text += delta;
        setLive({ chatId: next.id, text });
      });
    } catch (error) {
      interrupted = true;
      const message = abort.signal.aborted
        ? "Đã dừng phản hồi."
        : error instanceof TypeError || error instanceof SyntaxError
          ? "Kết nối hoặc phản hồi có lỗi. Bạn có thể thử lại."
          : error instanceof Error ? error.message : "Không gửi được tin nhắn.";
      setIssues((current) => ({ ...current, [next.id]: message }));
    } finally {
      if (text) {
        const reply: Message = { id: crypto.randomUUID(), role: "assistant", text, interrupted };
        const finished = { ...next, messages: [...next.messages, reply] };
        setChats((current) => current.map((item) => item.id === next.id ? finished : item));
        persist(finished);
      }
      controller.current = null;
      setLive(null);
    }
  }

  function send(event: FormEvent) {
    event.preventDefault();
    if (!loaded || controller.current || readingDraft || (!draft.text.trim() && !draft.files.length)) return;
    const text = draft.text.trim();
    const message: Message = {
      id: crypto.randomUUID(), role: "user", text, attachments: draft.files,
    };
    const title = Array.from((text || draft.files[0]?.name || "").replace(/\s+/g, " ")).slice(0, 80).join("");
    const next: Chat = chat
      ? { ...chat, updatedAt: Date.now(), messages: [...chat.messages, message] }
      : { id: crypto.randomUUID(), title, updatedAt: Date.now(), messages: [message] };
    const body = makeRequest(next);
    if (new Blob([body]).size > maxRequestBytes) {
      updateDraft(draftKey, { issue: "Chat vượt quá giới hạn dung lượng. Hãy bớt tệp hoặc tạo chat mới." });
      return;
    }
    setChats((current) => [next, ...current.filter(({ id }) => id !== next.id)]);
    persist(next);
    updateDraft(draftKey, emptyDraft);
    openChat(next.id);
    void run(next, body);
  }

  function retry() {
    if (controller.current || !chat || !last || (last.role !== "user" && !last.interrupted)) return;
    const next = last.interrupted ? { ...chat, messages: chat.messages.slice(0, -1) } : chat;
    const body = makeRequest(next);
    if (new Blob([body]).size > maxRequestBytes) {
      setIssues((current) => ({ ...current, [next.id]: "Chat vượt quá giới hạn dung lượng của máy chủ." }));
      return;
    }
    follow.current = true;
    setChats((current) => current.map((item) => item.id === next.id ? next : item));
    persist(next);
    void run(next, body);
  }

  function onPromptKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function submitModal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!modal) return;
    const value = String(new FormData(event.currentTarget).get("value") ?? "").trim();
    if (modal.kind === "key") setApiKey(value);
    if (modal.kind === "rename" && value) {
      const item = chats.find(({ id }) => id === modal.chat?.id);
      if (item && item.id !== live?.chatId) {
        const renamed = { ...item, title: value };
        setChats((current) => current.map((chat) => chat.id === item.id ? renamed : chat));
        persist(renamed);
      }
    }
    if (modal.kind === "delete" && modal.chat && modal.chat.id !== live?.chatId) {
      const id = modal.chat.id;
      persist(id);
      setChats((current) => current.filter((item) => item.id !== id));
      setDrafts(({ [id]: discarded, ...current }) => current);
      setIssues(({ [id]: discarded, ...current }) => current);
      if (selectedId === id) openChat(null);
    }
    setModal(null);
  }

  async function copy(message: Message) {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopiedId(message.id);
    } catch {
      if (selectedId) setIssues((current) => ({ ...current, [selectedId]: "Không sao chép được vào clipboard." }));
    }
  }

  return (
    <>
      <Sidebar collapsible="offcanvas">
        <SidebarHeader className="gap-5 p-4 pb-3">
          <div className="flex items-center gap-3 px-1">
            <div className="brand-mark" aria-hidden="true"><Sparkles /></div>
            <span className="text-lg font-semibold tracking-tight">Laris Chat</span>
          </div>
          <Button className="new-chat w-full justify-start" onClick={() => openChat(null)}>
            <Plus /> Chat mới
          </Button>
          {/* the research-gap pipeline: papers read, rules, baselines and judgements (T272) */}
          <a href="/gap" className="flex items-center gap-2 rounded-md border border-sidebar-border px-3 py-2 text-sm text-sidebar-foreground hover:bg-sidebar-accent">
            <Sparkles className="size-4" /> Tìm khoảng trống nghiên cứu
          </a>
          <InputGroup className="sidebar-search h-9">
            <InputGroupAddon><Search /></InputGroupAddon>
            <InputGroupInput
              aria-label="Tìm cuộc chat"
              placeholder="Tìm cuộc chat"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </InputGroup>
        </SidebarHeader>
        <SidebarContent className="px-2">
          <SidebarGroup>
            <SidebarGroupLabel>Lịch sử</SidebarGroupLabel>
            <SidebarMenu>
              {matching.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton
                    isActive={item.id === selectedId}
                    aria-current={item.id === selectedId ? "page" : undefined}
                    onClick={() => openChat(item.id)}
                    title={item.title}
                  >
                    <MessageSquare /><span>{item.title}</span>
                  </SidebarMenuButton>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <SidebarMenuAction aria-label={`Tùy chọn cho ${item.title}`}><MoreHorizontal /></SidebarMenuAction>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      <DropdownMenuItem disabled={live?.chatId === item.id} onSelect={() => setModal({ kind: "rename", chat: item })}>
                        <Pencil /> Đổi tên
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        disabled={live?.chatId === item.id}
                        onSelect={() => setModal({ kind: "delete", chat: item })}
                      >
                        <Trash2 /> Xóa chat
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
            {matching.length === 0 && (
              <p className="px-2 py-2 text-sm text-sidebar-foreground/65">
                {search ? "Không tìm thấy cuộc chat." : "Chưa có cuộc chat nào."}
              </p>
            )}
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="border-t border-sidebar-border p-4">
          <p className="px-1 text-xs text-sidebar-foreground/65">Lịch sử lưu trong trình duyệt này.</p>
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-h-0 min-w-0">
        <header className="flex h-15 shrink-0 items-center gap-3 border-b px-4 sm:px-6">
          <SidebarTrigger aria-label="Mở hoặc đóng thanh bên" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{chat?.title ?? "Chat mới"}</span>
          {live && !active && (
            <Button variant="outline" size="sm" onClick={() => openChat(live.chatId)}>
              Xem chat đang trả lời
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setModal({ kind: "key" })}>
            <KeyRound /> {apiKey ? "Đổi khóa API" : "Khóa API"}
          </Button>
        </header>
        {storageIssue && <Alert className="mx-auto mt-2 w-auto max-w-[95%]" role="status">
          <AlertDescription>{storageIssue}</AlertDescription>
        </Alert>}
        <div
          className={`relative flex min-h-0 flex-1 flex-col ${chat ? "" : "justify-center overflow-y-auto"}`}
          onDragEnter={(event) => {
            if (!event.dataTransfer.types.includes("Files")) return;
            event.preventDefault();
            dragDepth.current += 1;
            setDragging(true);
          }}
          onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); }}
          onDragLeave={() => {
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (dragDepth.current === 0) setDragging(false);
          }}
          onDrop={dropFiles}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-3 z-10 grid place-items-center rounded-2xl border-2 border-dashed border-primary bg-background/95 text-lg font-semibold">
              Thả tệp văn bản để đính kèm
            </div>
          )}
          {chat ? (
            <div
              ref={viewport}
              className="min-h-0 flex-1 overflow-y-auto"
              onScroll={(event) => {
                const { scrollHeight, clientHeight, scrollTop } = event.currentTarget;
                follow.current = scrollHeight - clientHeight - scrollTop < 80;
              }}
              aria-label="Nội dung cuộc chat"
              tabIndex={0}
            >
              <ol className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 py-6 sm:px-6 sm:py-9">
                {chat.messages.map((message) => (
                  <li key={message.id} className={message.role === "user" ? "flex justify-end" : "min-w-0"}>
                    {message.role === "user" ? (
                      <div className="user-message">
                        <span className="sr-only">Bạn</span>
                        {!!message.attachments?.length && (
                          <div className="mb-2 flex flex-wrap justify-end gap-1.5">
                            {message.attachments.map((file) => (
                              <Badge key={file.id} variant="outline" className="max-w-full bg-background" title={file.name}>
                                <FileText /><span className="truncate">{file.name}</span>
                              </Badge>
                            ))}
                          </div>
                        )}
                        <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{message.text}</p>
                      </div>
                    ) : (
                      <>
                        <div className="reply-label"><Sparkles /> Laris</div>
                        <div className="markdown">
                          <Markdown remarkPlugins={[remarkGfm]} skipHtml components={{
                            img: ({ alt }) => alt ? <span>{alt}</span> : null,
                          }}>{message.text}</Markdown>
                        </div>
                        {message.interrupted && <p className="mt-2 text-sm text-muted-foreground">Phản hồi chưa hoàn tất</p>}
                        <Button variant="ghost" size="icon-sm" className="mt-2 text-muted-foreground"
                          aria-label={copiedId === message.id ? "Đã sao chép" : "Sao chép phản hồi"}
                          onClick={() => void copy(message)}>
                          {copiedId === message.id ? <Check /> : <Copy />}
                        </Button>
                      </>
                    )}
                  </li>
                ))}
                {active && live && (
                  <li className="min-w-0">
                    <div className="reply-label"><Sparkles /> Laris</div>
                    <div className="markdown whitespace-pre-wrap [overflow-wrap:anywhere]">
                      {live.text || <span className="text-muted-foreground" role="status">Đang chờ phản hồi…</span>}
                    </div>
                  </li>
                )}
              </ol>
            </div>
          ) : (
            <section className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-6 text-center sm:px-6 sm:pb-8">
              <div className="brand-mark welcome-mark mx-auto mb-4" aria-hidden="true"><Sparkles /></div>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Bạn muốn khám phá gì?</h1>
              <p className="mt-3 text-base text-muted-foreground">Hỏi một câu hoặc đính kèm tài liệu để bắt đầu.</p>
            </section>
          )}

          <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4 sm:px-6 sm:pb-5">
            {issue && <Alert className="mb-2" role="status"><AlertDescription>{issue}</AlertDescription></Alert>}
            {!active && last && (last.interrupted || last.role === "user") && (
              <Button variant="outline" size="sm" className="mb-2" disabled={!!live} onClick={retry}>Thử lại</Button>
            )}
            <form onSubmit={send}>
              <input ref={fileInput} type="file" multiple accept={fileAccept} onChange={chooseFiles}
                hidden aria-label="Chọn tệp văn bản" />
              <InputGroup className="composer h-auto rounded-[1.15rem] bg-card">
                {draft.files.length > 0 && (
                  <InputGroupAddon align="block-start" className="flex-wrap gap-2 px-3 pt-3">
                    {draft.files.map((file) => (
                      <Badge key={file.id} variant="secondary" className="h-8 max-w-full gap-2 rounded-lg pl-2.5 pr-1">
                        <FileText /><span className="truncate" title={file.name}>{file.name}</span>
                        <Button type="button" variant="ghost" size="icon-xs" aria-label={`Bỏ tệp ${file.name}`}
                          onClick={() => updateDraft(draftKey, { files: draft.files.filter(({ id }) => id !== file.id), issue: "" })}>
                          <X />
                        </Button>
                      </Badge>
                    ))}
                  </InputGroupAddon>
                )}
                <InputGroupTextarea
                  ref={prompt}
                  rows={chat ? 2 : 3}
                  aria-label="Tin nhắn"
                  placeholder="Nhắn cho Laris…"
                  value={draft.text}
                  onChange={(event) => updateDraft(draftKey, { text: event.target.value, issue: "" })}
                  onKeyDown={onPromptKey}
                  className="max-h-44 resize-none px-4 py-3 !text-base"
                />
                <InputGroupAddon align="block-end" className="justify-between px-3 pb-3">
                  <InputGroupButton type="button" variant="ghost" size="sm" className="text-muted-foreground"
                    onClick={() => fileInput.current?.click()} disabled={readingDraft}
                    title="Tệp văn bản UTF-8: TXT, Markdown, CSV, JSON…">
                    <Paperclip /> {readingDraft ? "Đang đọc tệp…" : "Đính kèm"}
                  </InputGroupButton>
                  {active ? (
                  <InputGroupButton type="button" size="icon-sm" variant="default" aria-label="Dừng phản hồi"
                      onClick={() => controller.current?.abort()}><Square className="fill-current" /></InputGroupButton>
                  ) : (
                    <InputGroupButton type="submit" size="icon-sm" variant="default" aria-label="Gửi tin nhắn"
                      disabled={!loaded || !!live || readingDraft || (!draft.text.trim() && !draft.files.length)}><Send /></InputGroupButton>
                  )}
                </InputGroupAddon>
              </InputGroup>
              {draft.issue && <p className="mt-2 text-sm text-destructive" role="alert">{draft.issue}</p>}
            </form>
            {!chat ? (
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {suggestions.map(({ icon: Icon, label, text }) => (
                  <Button key={label} variant="outline" size="sm" className="rounded-full bg-card text-muted-foreground"
                    onClick={() => {
                      updateDraft(draftKey, { text });
                      prompt.current?.focus();
                    }}><Icon /> {label}</Button>
                ))}
              </div>
            ) : (
              <p className="mt-2 hidden text-center text-xs text-muted-foreground sm:block">Enter để gửi · Shift + Enter để xuống dòng</p>
            )}
          </div>
        </div>
      </SidebarInset>

      <Dialog open={!!modal} onOpenChange={(open) => { if (!open) setModal(null); }}>
        {modal && (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{modal.kind === "key" ? "Khóa API Laris" : modal.kind === "rename" ? "Đổi tên chat" : "Xóa cuộc chat?"}</DialogTitle>
              <DialogDescription>
                {modal.kind === "key" ? "Khóa chỉ dùng trong tab này. Bạn cần nhập lại sau khi tải lại trang." :
                  modal.kind === "rename" ? "Tên dùng để tìm lại cuộc chat trong lịch sử." :
                    "Lịch sử và nội dung tệp đính kèm của cuộc chat này sẽ bị xóa khỏi trình duyệt."}
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={submitModal} className="grid gap-4">
              {modal.kind !== "delete" && (
                <div className="grid gap-2">
                  <Label htmlFor="dialog-value">{modal.kind === "key" ? "Khóa API" : "Tên cuộc chat"}</Label>
                  <Input id="dialog-value" name="value" maxLength={modal.kind === "rename" ? 80 : undefined}
                    defaultValue={modal.kind === "key" ? apiKey : modal.chat?.title}
                    type={modal.kind === "key" ? "password" : "text"}
                    autoComplete="off" required={modal.kind === "rename"} />
                </div>
              )}
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setModal(null)}>Hủy</Button>
                <Button type="submit" variant={modal.kind === "delete" ? "destructive" : "default"}>
                  {modal.kind === "delete" ? "Xóa chat" : "Lưu"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
