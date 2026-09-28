import React from "react";
import { AlertCircle } from "lucide-react";
import { PillButton } from "../ui/PillButton";

export interface DeleteConfirmTarget {
  type: "provider" | "model";
  id: string;
  name: string;
}

interface DeleteConfirmDialogProps {
  target: DeleteConfirmTarget | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export const DeleteConfirmDialog: React.FC<DeleteConfirmDialogProps> = ({
  target,
  onCancel,
  onConfirm,
}) => {
  if (!target) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-zinc-900/40 backdrop-blur-xs animate-fade-in">
      <div
        className="w-full max-w-sm bg-white border border-zinc-200 rounded-3xl shadow-xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-full bg-rose-50 border border-rose-200/60 flex items-center justify-center text-rose-600 shrink-0">
            <AlertCircle className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-zinc-900">
              确认删除{target.type === "provider" ? "供应商" : "模型"}？
            </h3>
            <p className="text-xs text-zinc-500 mt-1 leading-relaxed">
              确定删除“{target.name}”？此操作将从配置中永久移除，不可撤销。
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <PillButton
            variant="secondary"
            size="sm"
            onClick={onCancel}
          >
            取消
          </PillButton>
          <PillButton
            variant="danger"
            size="sm"
            onClick={onConfirm}
          >
            确认删除
          </PillButton>
        </div>
      </div>
    </div>
  );
};
