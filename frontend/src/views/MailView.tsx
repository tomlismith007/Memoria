import React, { useEffect, useState } from "react";
import {
  Archive,
  CheckCircle2,
  Inbox,
  Mail,
  RefreshCw,
  ShieldCheck,
  Tag,
} from "lucide-react";
import { api } from "../api";
import type { MailItem } from "../types";
import { ConfirmModal } from "../components/ui/ConfirmModal";
import { PillBadge } from "../components/ui/PillBadge";
import { PillButton } from "../components/ui/PillButton";
import { RoundedCard } from "../components/ui/RoundedCard";

export const MailView: React.FC = () => {
  const [mails, setMails] = useState<MailItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const loadMails = async () => {
    setLoading(true);
    setStatusMessage(null);
    try {
      const data = await api.getMailTriage();
      setMails(data.triages || []);
    } catch (err: any) {
      alert(`获取邮件列表失败: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMails();
  }, []);

  const protectedMails = mails.filter((m) => m.protected);
  const candidateMails = mails.filter((m) => !m.protected && m.can_archive);
  const normalMails = mails.filter((m) => !m.protected && !m.can_archive);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const selectAllCandidates = () => {
    if (selectedIds.length === candidateMails.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(candidateMails.map((m) => m.id));
    }
  };

  const handleConfirmArchive = async () => {
    if (selectedIds.length === 0) return;
    setArchiving(true);
    try {
      const res = await api.archiveMail(selectedIds);
      setStatusMessage(res.message);
      setModalOpen(false);
      setSelectedIds([]);
      await loadMails();
    } catch (err: any) {
      alert(`归档操作失败: ${err.message}`);
    } finally {
      setArchiving(false);
    }
  };

  const selectedCandidateItems = candidateMails
    .filter((m) => selectedIds.includes(m.id))
    .map((m) => ({ id: m.id, subject: m.subject, summary: m.summary }));

  return (
    <div className="min-w-0 space-y-6 animate-fade-in max-w-4xl mx-auto">
      {/* Header & Invariants Banner */}
      <div className="flex flex-col items-start gap-3 border-b border-zinc-200/80 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl md:text-2xl font-semibold text-zinc-900 tracking-tight flex items-start sm:items-center gap-2 break-words">
            <Mail className="w-5 h-5 text-zinc-700 shrink-0" />
            <span>AI 邮件安全分拣中心</span>
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            两级智能分拣：规则层守护验证码/交易特征，LLM 提炼一句话摘要。归档必须人工二次确认。
          </p>
        </div>
        <PillButton
          variant="outline"
          size="sm"
          onClick={loadMails}
          disabled={loading}
          icon={<RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />}
        >
          刷新收件箱
        </PillButton>
      </div>

      {statusMessage && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-2xl p-4 text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
          <span>{statusMessage}</span>
        </div>
      )}

      {/* 1. Protected Section (Red Line) */}
      <div className="space-y-3">
        <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-amber-600" />
              受保护邮件（验证码 / 交易账单 — 永不可归档）
            </span>
            <span className="text-[11px] bg-amber-100 text-amber-800 rounded-full px-2 py-0.2">
              {protectedMails.length} 封
            </span>
          </div>
          <span className="text-[11px] text-amber-700/80 font-mono">红线保护 · 物理级只读</span>
        </div>

        {protectedMails.length === 0 ? (
          <RoundedCard variant="item" className="text-center py-6 text-xs text-zinc-400">
            暂无受保护邮件
          </RoundedCard>
        ) : (
          <div className="space-y-2.5">
            {protectedMails.map((m) => (
              <RoundedCard
                key={m.id}
                variant="amber"
                className="flex flex-col items-stretch justify-between gap-4 sm:flex-row"
              >
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <PillBadge variant="protected">
                      <ShieldCheck className="w-3 h-3" />
                      交易/验证码保护
                    </PillBadge>
                    <span className="min-w-0 break-words font-medium text-xs text-zinc-900">
                      {m.subject}
                    </span>
                  </div>
                  <div className="min-w-0 break-words text-xs text-zinc-600">
                    <strong>摘要：</strong> {m.summary}
                  </div>
                  <div className="text-[11px] text-zinc-400 font-mono">
                    发件人: {m.sender || "未知"}
                  </div>
                </div>

                <div className="shrink-0 text-right">
                  <span className="text-[11px] font-mono text-amber-800 bg-amber-100/80 rounded-full px-2.5 py-1 select-none">
                    受系统保护
                  </span>
                </div>
              </RoundedCard>
            ))}
          </div>
        )}
      </div>

      {/* 2. Marketing / Archive Candidate Section */}
      <div className="space-y-3 pt-4">
        <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-zinc-700 uppercase tracking-wider flex items-center gap-1.5">
              <Archive className="w-4 h-4 text-rose-600" />
              营销推广邮件（建议归档候选）
            </span>
            <span className="text-[11px] bg-zinc-200 text-zinc-700 rounded-full px-2 py-0.2">
              {candidateMails.length} 封
            </span>
          </div>

          {candidateMails.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <PillButton
                variant="secondary"
                size="sm"
                onClick={selectAllCandidates}
              >
                {selectedIds.length === candidateMails.length ? "取消全选" : "全选"}
              </PillButton>
              <PillButton
                variant="danger"
                size="sm"
                onClick={() => setModalOpen(true)}
                disabled={selectedIds.length === 0}
                icon={<Archive className="w-3.5 h-3.5" />}
              >
                归档选中的 ({selectedIds.length}) 封
              </PillButton>
            </div>
          )}
        </div>

        {candidateMails.length === 0 ? (
          <RoundedCard variant="item" className="text-center py-6 text-xs text-zinc-400">
            暂无营销推广邮件
          </RoundedCard>
        ) : (
          <div className="space-y-2.5">
            {candidateMails.map((m) => {
              const isChecked = selectedIds.includes(m.id);
              return (
                <RoundedCard
                  key={m.id}
                  variant="rose"
                  className={`flex flex-col items-stretch justify-between gap-4 transition-all cursor-pointer sm:flex-row ${
                    isChecked ? "ring-2 ring-rose-400/60 bg-rose-50/50" : ""
                  }`}
                  onClick={() => toggleSelect(m.id)}
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggleSelect(m.id)}
                      className="mt-1 rounded text-zinc-900 cursor-pointer"
                      onClick={(e) => e.stopPropagation()}
                    />
                    <div className="space-y-1">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <PillBadge variant="candidate">营销推广</PillBadge>
                        <span className="min-w-0 break-words font-medium text-xs text-zinc-900">
                          {m.subject}
                        </span>
                      </div>
                      <div className="min-w-0 break-words text-xs text-zinc-600">
                        <strong>摘要：</strong> {m.summary}
                      </div>
                      <div className="text-[11px] text-zinc-400 font-mono">
                        发件人: {m.sender || "未知"}
                      </div>
                    </div>
                  </div>
                </RoundedCard>
              );
            })}
          </div>
        )}
      </div>

      {/* 3. Normal Notices / Tasks Section */}
      {normalMails.length > 0 && (
        <div className="space-y-3 pt-4">
          <div className="text-xs font-semibold text-zinc-700 uppercase tracking-wider flex items-center gap-1.5">
            <Inbox className="w-4 h-4 text-zinc-500" />
            日常通知与待办 ({normalMails.length} 封)
          </div>
          <div className="space-y-2">
            {normalMails.map((m) => (
              <RoundedCard key={m.id} variant="item" className="space-y-1">
                <div className="flex items-center gap-2">
                  <PillBadge variant="neutral">{m.category}</PillBadge>
                  <span className="font-medium text-xs text-zinc-900">
                    {m.subject}
                  </span>
                </div>
                <div className="text-xs text-zinc-600">
                  {m.summary}
                </div>
              </RoundedCard>
            ))}
          </div>
        </div>
      )}

      {/* Strict Human Confirmation Modal */}
      <ConfirmModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        onConfirm={handleConfirmArchive}
        title="确认执行邮件归档？"
        description="请核对以下待从收件箱移除的营销邮件"
        items={selectedCandidateItems}
        loading={archiving}
      />
    </div>
  );
};
