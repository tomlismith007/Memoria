import React from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { PillButton } from "./PillButton";

interface ConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  items: { id: string; subject: string; summary: string }[];
  loading?: boolean;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  items,
  loading = false,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-zinc-900/40 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-3xl border border-zinc-200 shadow-xl max-w-lg w-full p-6 md:p-8 space-y-5">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-rose-50 border border-rose-200/60 flex items-center justify-center text-rose-600">
              <AlertCircle className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-zinc-900">{title}</h3>
              <p className="text-xs text-zinc-500 mt-0.5">{description}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-zinc-400 hover:text-zinc-700 hover:bg-zinc-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="border border-zinc-100 rounded-2xl bg-zinc-50/70 p-3 max-h-56 overflow-y-auto space-y-2">
          {items.map((item) => (
            <div
              key={item.id}
              className="bg-white rounded-xl border border-zinc-200/70 p-2.5 text-xs space-y-1"
            >
              <div className="font-medium text-zinc-900 truncate">
                {item.subject}
              </div>
              <div className="text-zinc-500 text-[11px] truncate">
                {item.summary}
              </div>
            </div>
          ))}
        </div>

        <div className="text-xs text-zinc-500 leading-relaxed bg-amber-50/60 border border-amber-200/60 rounded-xl p-3">
          <strong>系统安全守则</strong>：验证码与交易邮件永远受物理级保护，绝不进入此列表。此操作经你确认后，将从收件箱移除选中的营销邮件标签。
        </div>

        <div className="flex items-center justify-end gap-2.5 pt-2">
          <PillButton variant="secondary" onClick={onClose} disabled={loading}>
            取消
          </PillButton>
          <PillButton
            variant="danger"
            onClick={onConfirm}
            disabled={loading || items.length === 0}
            icon={<CheckCircle2 className="w-4 h-4" />}
          >
            {loading ? "处理中..." : `确认归档 ${items.length} 封邮件`}
          </PillButton>
        </div>
      </div>
    </div>
  );
};
