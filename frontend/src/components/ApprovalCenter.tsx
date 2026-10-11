import React, { useCallback, useEffect, useState } from "react";
import {
  Bell,
  CheckCircle2,
  FileWarning,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { api } from "../api";
import type { AppNotification, Proposal } from "../types";
import { PillBadge } from "./ui/PillBadge";
import { PillButton } from "./ui/PillButton";

const STATUS_LABEL: Record<string, string> = {
  awaiting_review: "待审",
  executing: "执行中",
  succeeded: "已执行",
  failed: "失败",
  outcome_unknown: "结果未知",
  denied: "已拒绝",
  cancelled: "已取消",
  expired: "已过期",
};

const STATUS_VARIANT: Record<
  string,
  "wiki" | "protected" | "candidate" | "warning" | "neutral"
> = {
  awaiting_review: "warning",
  executing: "candidate",
  succeeded: "wiki",
  failed: "candidate",
  outcome_unknown: "candidate",
  denied: "neutral",
  cancelled: "neutral",
  expired: "neutral",
};

const KIND_LABEL: Record<string, string> = {
  archive: "归档邮件",
  delete_doc: "删除文档",
  reindex: "重建向量索引",
};

function PayloadDetail({ proposal }: { proposal: Proposal }) {
  if (proposal.kind === "archive" && proposal.payload.msgs) {
    return (
      <div className="space-y-1.5">
        {proposal.payload.msgs.map((m) => (
          <div
            key={m.msg_id}
            className="bg-white rounded-xl border border-zinc-200/70 px-2.5 py-2 text-xs"
          >
            <div className="font-medium text-zinc-900 truncate">{m.subject}</div>
            <div className="text-zinc-500 text-[11px] truncate">
              {m.sender} · {m.category}
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (proposal.kind === "delete_doc") {
    return (
      <p className="text-xs text-zinc-600 break-words">
        将删除文档「{proposal.payload.name || proposal.payload.doc_id}」的全部向量与 raw 原文。
      </p>
    );
  }
  return (
    <p className="text-xs text-zinc-600">
      将清空向量集合并按当前向量模型重建 {proposal.payload.raw_files ?? "?"} 篇原始文档。
    </p>
  );
}

interface ApprovalCenterProps {
  isOpen: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export const ApprovalCenter: React.FC<ApprovalCenterProps> = ({
  isOpen,
  onClose,
  onChanged,
}) => {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [proposalData, notificationData] = await Promise.all([
        api.listProposals(),
        api.listNotifications(true),
      ]);
      setProposals(proposalData.proposals);
      setNotifications(notificationData.notifications);
    } catch {
      // listing is best-effort; keep whatever we had
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);

  if (!isOpen) return null;

  const decide = async (proposal: Proposal, decision: "approved" | "denied") => {
    setBusyId(proposal.id);
    try {
      await api.decideProposal(proposal.id, decision, proposal.content_hash);
      await load();
      onChanged();
    } catch (err: any) {
      alert(`提案处理失败: ${err.message}`);
    } finally {
      setBusyId(null);
    }
  };

  const markRead = async (notification: AppNotification) => {
    try {
      await api.markNotificationRead(notification.id);
      await load();
    } catch (err: any) {
      alert(`标记已读失败: ${err.message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-900/40 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-3xl border border-zinc-200 shadow-xl max-w-lg w-full p-6 md:p-8 space-y-5 max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-zinc-900 flex items-center justify-center text-white">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-zinc-900">审批中心</h3>
              <p className="text-xs text-zinc-500 mt-0.5">
                破坏性动作的唯一执行通道；提案 30 分钟内有效。
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={load}
              title="刷新"
              className="rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={onClose}
              className="rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto space-y-3 pr-0.5">
          {notifications.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-[11px] font-medium text-zinc-400">
                <Bell className="w-3 h-3" /> 运行动态（定时任务）
              </div>
              {notifications.map((n) => (
                <div
                  key={n.id}
                  className="rounded-xl border border-zinc-200/80 bg-blue-50/50 px-3 py-2 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-zinc-900">{n.title}</span>
                    <button
                      onClick={() => markRead(n)}
                      className="text-[11px] text-zinc-400 hover:text-zinc-700 shrink-0"
                    >
                      标为已读
                    </button>
                  </div>
                  <p className="text-zinc-600 break-words">{n.body}</p>
                  <span className="text-[10px] text-zinc-400 font-mono">
                    {new Date(n.created_at).toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          )}

          {proposals.length === 0 && notifications.length === 0 && !loading && (
            <div className="text-center text-xs text-zinc-400 py-8">
              暂无提案记录
            </div>
          )}
          {proposals.map((p) => {
            const expired =
              p.status === "awaiting_review" && new Date(p.expires_at) < new Date();
            return (
              <div
                key={p.id}
                className="rounded-2xl border border-zinc-200/80 bg-zinc-50/70 p-3 space-y-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold text-zinc-900">
                    {KIND_LABEL[p.kind] ?? p.kind}
                  </span>
                  <PillBadge variant={STATUS_VARIANT[p.status] ?? "neutral"}>
                    {STATUS_LABEL[p.status] ?? p.status}
                  </PillBadge>
                  <span className="text-[10px] text-zinc-400 font-mono truncate">
                    到期 {new Date(p.expires_at).toLocaleString()}
                  </span>
                </div>
                {p.status !== "denied" && p.status !== "expired" && (
                  <PayloadDetail proposal={p} />
                )}
                {p.error && (
                  <p className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200/60 rounded-xl px-2.5 py-1.5 break-words">
                    {p.error}
                  </p>
                )}
                {p.status === "awaiting_review" && !expired && (
                  <div className="flex items-center justify-end gap-2 pt-0.5">
                    <PillButton
                      variant="secondary"
                      size="sm"
                      onClick={() => decide(p, "denied")}
                      disabled={busyId === p.id}
                    >
                      拒绝
                    </PillButton>
                    <PillButton
                      variant="danger"
                      size="sm"
                      icon={<CheckCircle2 className="w-3.5 h-3.5" />}
                      onClick={() => decide(p, "approved")}
                      disabled={busyId === p.id}
                    >
                      {busyId === p.id ? "处理中..." : "批准执行"}
                    </PillButton>
                  </div>
                )}
                {p.status === "awaiting_review" && expired && (
                  <p className="text-[11px] text-zinc-500 flex items-center gap-1">
                    <FileWarning className="w-3 h-3" /> 已超过有效期，等待后台清理。
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
