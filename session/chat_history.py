# session/chat_history.py
# Java: package com.lcallai;
import json
from typing import List, Optional


class ChatHistory:
    """
    public class ChatHistory {
        int max_ask_history_to_ai = 10;
        private final LinkedList<Message> messages = new LinkedList<>();
    }
    """

    # Java: public ChatHistory(int size) { max_ask_history_to_ai = size; }
    def __init__(self, size: int = 10):
        # Java: int max_ask_history_to_ai = 10;
        self.max_ask_history_to_ai = size
        # Java: private final LinkedList<Message> messages = new LinkedList<>();
        self._messages: List[dict] = []

    """
    public void addMessage(String role, String content) {
        if ("system".equalsIgnoreCase(role)) {
            // 删除已有 system 消息
            Iterator<Message> iterator = messages.iterator();
            while (iterator.hasNext()) {
                if ("system".equalsIgnoreCase(iterator.next().getRole())) {
                    iterator.remove();
                    break;
                }
            }
            // 插入到首位
            messages.addFirst(new Message("system", content));
        } else {
            messages.addLast(new Message(role, content));
        }
    }
    """
    def addMessage(self, role: str, content: str) -> None:
        if role.lower() == "system":
            # Java: 删除已有 system，只保留一条，插入首位
            self._messages = [m for m in self._messages if m["role"].lower() != "system"]
            self._messages.insert(0, {"role": role, "content": content})
        else:
            # Java: messages.addLast(new Message(role, content));
            self._messages.append({"role": role, "content": content})

    """
    public void trim(int maxSize) {
        if (maxSize <= 0) return;
        while (messages.size() > maxSize) {
            if (!messages.isEmpty()
                    && "system".equalsIgnoreCase(messages.getFirst().getRole())) {
                // 保留 system，从索引 1 删除
                messages.remove(1);
            } else {
                messages.removeFirst();
            }
        }
    }
    """
    def trim(self, maxSize: int) -> None:
        # Java: if (maxSize <= 0) return;
        if maxSize <= 0:
            return
        # Java: while (messages.size() > maxSize)
        while len(self._messages) > maxSize:
            if (self._messages
                    and self._messages[0]["role"].lower() == "system"):
                # Java: 保留 system，从索引 1 删除
                if len(self._messages) > 1:
                    self._messages.pop(1)
                else:
                    break
            else:
                # Java: messages.removeFirst();
                self._messages.pop(0)

    """
    public ArrayNode toJsonArrayWithWindow() {
        int windowSize = max_ask_history_to_ai;
        ArrayNode arrayNode = ...;

        // 1. 始终强制保留 System Message
        if (!messages.isEmpty()
                && "system".equalsIgnoreCase(messages.getFirst().getRole())) {
            arrayNode.add(sysNode);
        }

        // 2. 计算滑动窗口的起始点（排除 system 后从哪里开始截取）
        int size = messages.size();
        int startIndex = Math.max(1, size - windowSize);

        // 3. 只把最近的 windowSize 条消息加进去
        for (int i = startIndex; i < size; i++) {
            arrayNode.add(node);
        }
        return arrayNode;
    }
    """
    def toJsonArrayWithWindow(self) -> List[dict]:
        windowSize = self.max_ask_history_to_ai
        result = []

        # Java: 始终强制保留 System Message
        if self._messages and self._messages[0]["role"].lower() == "system":
            result.append(self._messages[0])

        # Java: int startIndex = Math.max(1, size - windowSize);
        size       = len(self._messages)
        startIndex = max(1, size - windowSize)

        # Java: for (int i = startIndex; i < size; i++)
        for i in range(startIndex, size):
            result.append(self._messages[i])

        return result

    """
    public ArrayNode toJsonArray() {
        ArrayNode arrayNode = ...;
        for (Message msg : messages) {
            node.put("role", msg.getRole());
            node.put("content", msg.getContent());
            arrayNode.add(node);
        }
        return arrayNode;
    }
    """
    def toJsonArray(self) -> List[dict]:
        # Java: 完整列表，不做窗口截断
        return [{"role": m["role"], "content": m["content"]} for m in self._messages]

    """
    public List<Message> getMessages() {
        return List.copyOf(messages);
    }
    """
    def getMessages(self) -> List[dict]:
        # Java: return List.copyOf(messages); — 只读副本
        return list(self._messages)

    """
    public void clear() {
        messages.clear();
    }
    """
    def clear(self) -> None:
        self._messages.clear()

    """
    public String toPlainText(int windowSize) {
        StringBuilder sb = new StringBuilder();
        int size  = messages.size();
        int start = Math.max(1, size - windowSize);
        for (int i = start; i < size; i++) {
            Message msg = messages.get(i);
            if ("system".equalsIgnoreCase(msg.getRole())) continue;
            sb.append(msg.getRole()).append(": ").append(msg.getContent()).append("\n");
        }
        return sb.toString().trim();
    }
    """

    def toPlainText(self, windowSize: int) -> str:
        size  = len(self._messages)
        # 只有第一条是 system 时才从 index 1 开始，否则从 index 0
        has_system = self._messages and self._messages[0]["role"].lower() == "system"
        base_start = 1 if has_system else 0
        start = max(base_start, size - windowSize)
        lines = []
        for i in range(start, size):
            msg = self._messages[i]
            if msg["role"].lower() == "system":
                continue
            lines.append(msg["role"] + ": " + msg.get("content", ""))
        return "\n".join(lines).strip()

    def __len__(self) -> int:
        return len(self._messages)

    def __repr__(self) -> str:
        return "ChatHistory(size=" + str(len(self._messages)) + ")"
    def __reversed__(self):
        return reversed(self._messages)