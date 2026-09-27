import React from "react";
import { X } from "lucide-react";
import { PillButton } from "../ui/PillButton";
import { splitTags, type ProviderConfigCtrl } from "./useProviderConfig";

interface ModelFormDialogProps {
  ctrl: ProviderConfigCtrl;
}

/* Modal: Add/Edit Model Dialog */
export const ModelFormDialog: React.FC<ModelFormDialogProps> = ({ ctrl }) => {
  const {
    isAddModelOpen,
    setIsAddModelOpen,
    modelFormId,
    setModelFormId,
    modelFormName,
    setModelFormName,
    modelFormTags,
    setModelFormTags,
    editingModelOriginalId,
    handleSaveModel,
  } = ctrl;

  if (!isAddModelOpen) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-zinc-900/40 backdrop-blur-xs animate-fade-in">
      <div
        className="w-full max-w-md bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl shadow-xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {editingModelOriginalId ? "编辑模型" : "添加模型"}
          </h3>
          <button
            onClick={() => setIsAddModelOpen(false)}
            className="p-1 rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">
              模型 ID
            </label>
            <input
              type="text"
              value={modelFormId}
              onChange={(e) => setModelFormId(e.target.value)}
              disabled={Boolean(editingModelOriginalId)}
              placeholder="如 deepseek-chat, gpt-4o"
              className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">
              显示名称 (可选)
            </label>
            <input
              type="text"
              value={modelFormName}
              onChange={(e) => setModelFormName(e.target.value)}
              placeholder="如 DeepSeek V3"
              className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">
              标签 (用逗号分隔)
            </label>
            <input
              type="text"
              value={modelFormTags}
              onChange={(e) => setModelFormTags(e.target.value)}
              placeholder="如 128K, 视觉, 推理, Chat"
              className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10"
            />
            <div className="flex gap-1.5 mt-2 flex-wrap">
              {["128K", "1M", "视觉", "推理", "通用", "Embedding"].map((presetTag) => (
                <button
                  key={presetTag}
                  type="button"
                  onClick={() => {
                    const current = splitTags(modelFormTags);
                    if (!current.includes(presetTag)) {
                      setModelFormTags([...current, presetTag].join(", "));
                    }
                  }}
                  className="text-[11px] px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors cursor-pointer"
                >
                  +{presetTag}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <PillButton
            variant="secondary"
            size="sm"
            onClick={() => setIsAddModelOpen(false)}
          >
            取消
          </PillButton>
          <PillButton variant="primary" size="sm" onClick={handleSaveModel}>
            保存模型
          </PillButton>
        </div>
      </div>
    </div>
  );
};
