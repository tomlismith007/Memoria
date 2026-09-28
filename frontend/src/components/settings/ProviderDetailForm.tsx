import React from "react";
import {
  Activity,
  AlertCircle,
  Box,
  Check,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  Layers,
  Loader2,
  MoreVertical,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Zap,
} from "lucide-react";
import type { ModelApiFormat } from "../../types";
import { PillButton } from "../ui/PillButton";
import type { ProviderConfigCtrl } from "./useProviderConfig";

interface ProviderDetailFormProps {
  ctrl: ProviderConfigCtrl;
}

/* VIEW B: Provider Detail & Model Management Form */
export const ProviderDetailForm: React.FC<ProviderDetailFormProps> = ({ ctrl }) => {
  const {
    formName,
    setFormName,
    formBaseUrl,
    setFormBaseUrl,
    formApiFormat,
    setFormApiFormat,
    formApiKey,
    setFormApiKey,
    formEnabled,
    setFormEnabled,
    formChatModel,
    showApiKey,
    setShowApiKey,
    settingsTab,
    isCreatingNew,
    selectedProvider,
    activeProviderId,
    activeChatModel,
    activeEmbedProviderId,
    activeEmbedModel,
    fetchingModels,
    fetchedModels,
    modelSearchQuery,
    setModelSearchQuery,
    currentModelList,
    filteredFetchedModels,
    modelTestResults,
    testingModelId,
    testingConnection,
    connectionDiagnostics,
    setConnectionDiagnostics,
    saving,
    showMoreMenu,
    setShowMoreMenu,
    setModelFormId,
    setModelFormName,
    setModelFormTags,
    setEditingModelOriginalId,
    setIsAddModelOpen,
    setDeleteConfirm,
    handleCancelCreate,
    handleFetchModels,
    handleSelectModel,
    handleImportAllFetched,
    handleTestModel,
    handleTestConnection,
    handleSaveCurrentProvider,
    handleSaveNewProvider,
  } = ctrl;

  // Models the gateway offers that are not in this provider yet. Drives both the
  // "N 个待添加" count and the 全部添加 button, so a fully-imported provider reads
  // as finished instead of showing an empty block.
  const pendingFetchedCount = filteredFetchedModels.filter(
    (fm) => !currentModelList.some((m) => m.id === fm)
  ).length;

  return (
    <div className="p-5 sm:p-6 space-y-5 max-w-2xl animate-fade-in">
      {/* Provider Header Toolbar */}
      <div className="sticky top-0 z-10 -mx-5 sm:-mx-6 -mt-5 sm:-mt-6 px-5 sm:px-6 pt-5 sm:pt-6 pb-4 bg-white dark:bg-zinc-900 border-b border-zinc-100 dark:border-zinc-800 flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3 min-w-0 sm:flex-1 sm:mr-4">
          <div className="w-9 h-9 rounded-lg border border-zinc-200 bg-white flex items-center justify-center text-zinc-700 shrink-0 font-semibold text-xs">
            {formName.trim().slice(0, 2).toUpperCase() || <Cpu className="w-5 h-5" />}
          </div>
          <div className="flex-1 min-w-0">
            {isCreatingNew ? (
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="输入供应商名称"
                className="w-full max-w-sm px-1 -mx-1 py-0.5 text-base font-semibold text-zinc-900 dark:text-zinc-100 bg-transparent rounded-lg focus:outline-none focus:ring-1 focus:ring-zinc-300/70 dark:focus:ring-zinc-700 transition-all"
              />
            ) : (
              <h3 className="text-base font-semibold text-zinc-900 truncate">
                {formName || selectedProvider?.name}
              </h3>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 sm:gap-3 sm:shrink-0">
          {/* Active Switch */}
          <button
            type="button"
            onClick={() => setFormEnabled(!formEnabled)}
            title={formEnabled ? "已启用" : "已禁用"}
            className={`w-10 h-6 flex items-center rounded-full p-1 transition-colors duration-200 ease-in-out cursor-pointer ${
              formEnabled ? "bg-zinc-900" : "bg-zinc-300"
            }`}
          >
            <span
              className={`bg-white w-4 h-4 rounded-full shadow-sm transform transition-transform duration-200 ease-in-out ${
                formEnabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>

          {isCreatingNew ? (
            <button
              type="button"
              onClick={handleCancelCreate}
              className="px-2.5 py-1 text-xs text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-full transition-colors cursor-pointer"
            >
              取消
            </button>
          ) : (
            <>
              {/* More Action Menu */}
              <div className="relative">
                <button
                  onClick={() => setShowMoreMenu(!showMoreMenu)}
                  className="p-1.5 rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                >
                  <MoreVertical className="w-4 h-4" />
                </button>

                {showMoreMenu && (
                  <div
                    className="absolute right-0 mt-2 w-40 bg-white border border-zinc-200 rounded-xl shadow-lg py-1.5 z-30 animate-fade-in"
                    onClick={() => setShowMoreMenu(false)}
                  >
                    {settingsTab === "chat" && selectedProvider?.id !== activeProviderId && (
                      <button
                        type="button"
                        onClick={() =>
                          handleSelectModel(
                            formChatModel || selectedProvider?.models[0]?.id || ""
                          )
                        }
                        className="w-full text-left px-3.5 py-2 text-xs text-zinc-700 hover:bg-zinc-50 cursor-pointer"
                      >
                        设为当前
                      </button>
                    )}
                    <button
                      onClick={() =>
                        setDeleteConfirm({
                          type: "provider",
                          id: selectedProvider!.id,
                          name: selectedProvider!.name,
                        })
                      }
                      className="w-full text-left px-3.5 py-1.5 text-xs text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 flex items-center gap-2 cursor-pointer font-medium"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      删除供应商
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-zinc-700 mb-2">
            Base URL
          </label>
          <input
            type="text"
            value={formBaseUrl}
            onChange={(e) => setFormBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
            className="w-full px-3 py-2.5 text-sm bg-white border border-zinc-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-zinc-900/10 font-mono"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-zinc-700 mb-2">
            API 格式
          </label>
          <select
            value={formApiFormat}
            onChange={(e) => setFormApiFormat(e.target.value as ModelApiFormat)}
            className="w-full px-3 py-2.5 text-sm bg-white border border-zinc-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-zinc-900/10"
          >
            <option value="chat_completions">
              OpenAI 兼容 · Chat Completions
            </option>
            <option value="anthropic_messages">
              Claude · Anthropic Messages
            </option>
            <option value="openai_responses">
              OpenAI · Responses API
            </option>
          </select>
          {settingsTab === "embedding" && (
            <p className="text-[11px] text-zinc-400 mt-1.5">
              向量接口固定使用 OpenAI 兼容 /embeddings。
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-zinc-700 mb-2">
            API Key
          </label>
          <div className="relative">
            <input
              type={showApiKey ? "text" : "password"}
              value={formApiKey}
              onChange={(e) => setFormApiKey(e.target.value)}
              placeholder={
                !isCreatingNew && selectedProvider?.api_key_set
                  ? `•••••••••••• (${selectedProvider.masked_api_key || "已保存"})`
                  : "输入 API Key"
              }
              className="w-full pl-3 pr-10 py-2.5 text-sm bg-white border border-zinc-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-zinc-900/10 font-mono"
            />
            <button
              type="button"
              onClick={() => setShowApiKey(!showApiKey)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-700"
            >
              {showApiKey ? (
                <EyeOff className="w-4 h-4" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Model Selection & Quick Pills */}
      <div className="space-y-5 border-t border-zinc-100 pt-6">
        <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-zinc-700" />
            <h4 className="text-sm font-semibold text-zinc-900">
              模型
            </h4>
          </div>

          <div className="flex items-center gap-2">
            <PillButton
              variant="secondary"
              size="sm"
              onClick={handleFetchModels}
              disabled={fetchingModels || !formBaseUrl}
              icon={
                <RefreshCw
                  className={`w-3.5 h-3.5 ${fetchingModels ? "animate-spin text-zinc-900" : ""}`}
                />
              }
            >
              {fetchingModels ? "正在获取..." : "获取模型"}
            </PillButton>
            <PillButton
              variant="outline"
              size="sm"
              onClick={() => {
                setModelFormId("");
                setModelFormName("");
                setModelFormTags(settingsTab === "embedding" ? "Embedding" : "Chat, 128K");
                setEditingModelOriginalId(null);
                setIsAddModelOpen(true);
              }}
              icon={<Plus className="w-3.5 h-3.5" />}
            >
              添加模型
            </PillButton>
          </div>
        </div>

        {settingsTab === "embedding" && (
          <p className="text-[11px] text-zinc-400">
            切换向量模型可能影响既有向量索引，需要时请重建索引。
          </p>
        )}

        {/* Selectable Model Pills */}
        {fetchedModels.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">
                可用模型
                {/* Say what is still missing: after 全部添加 every pill moves to
                    the saved list and this block would otherwise look broken. */}
                {pendingFetchedCount > 0
                  ? `（${pendingFetchedCount} 个待添加）`
                  : "（已全部添加）"}
              </span>

              {pendingFetchedCount > 0 && (
                <button
                  type="button"
                  onClick={handleImportAllFetched}
                  className="text-[11px] text-zinc-500 hover:text-zinc-900 transition-colors"
                >
                  全部添加
                </button>
              )}
            </div>

            {(fetchedModels.length > 8 || currentModelList.length > 8) && (
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
                <input
                  type="text"
                  value={modelSearchQuery}
                  onChange={(e) => setModelSearchQuery(e.target.value)}
                  placeholder="筛选模型名称..."
                  className="w-full pl-8 pr-3 py-1 text-xs bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg focus:outline-none"
                />
              </div>
            )}

            <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto pt-1 pr-1">
              {currentModelList.map((m) => {
                const isCurrent = formChatModel === m.id;
                return (
                  <button
                    key={`p-${m.id}`}
                    type="button"
                    onClick={() => handleSelectModel(m.id, settingsTab)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono transition-all cursor-pointer ${
                      isCurrent
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-xs"
                        : "bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:border-zinc-400"
                    }`}
                  >
                    <span>{m.name || m.id}</span>
                    {isCurrent && <Check className="w-3 h-3" />}
                  </button>
                );
              })}

              {filteredFetchedModels
                .filter((fm) => !currentModelList.some((m) => m.id === fm))
                .map((fm) => {
                  const isCurrent = formChatModel === fm;
                  return (
                    <button
                      key={`f-${fm}`}
                      type="button"
                      onClick={() => handleSelectModel(fm, settingsTab)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono transition-all cursor-pointer ${
                        isCurrent
                          ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-xs"
                          : "bg-zinc-100/80 dark:bg-zinc-800 border border-dashed border-zinc-300 dark:border-zinc-600 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 hover:border-zinc-400"
                      }`}
                    >
                      <span>{fm}</span>
                      <Plus className="w-3 h-3 text-zinc-400" />
                    </button>
                  );
                })}
            </div>
          </div>
        )}
      </div>

      {/* Model List Section */}
      <div>

        {currentModelList.length === 0 ? (
          <div className="py-6 border border-dashed border-zinc-200 rounded-lg flex flex-col items-center justify-center text-center text-zinc-400 gap-1.5">
            <Layers className="w-5 h-5 text-zinc-300" />
            <p className="text-xs">暂无模型</p>
          </div>
        ) : (
          <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-100 dark:divide-zinc-800 overflow-hidden">
            {currentModelList.map((m) => {
              const isModelActive =
                !isCreatingNew &&
                (settingsTab === "chat"
                  ? selectedProvider?.id === activeProviderId &&
                    activeChatModel === m.id
                  : selectedProvider?.id === activeEmbedProviderId &&
                    activeEmbedModel === m.id);
              const isCurrentFormModel = formChatModel === m.id;
              const testState = modelTestResults[m.id];
              const isTesting = testingModelId === m.id;

              return (
                <div
                  key={m.id}
                  className={`flex flex-col items-stretch gap-2 px-3 py-2 transition-colors sm:flex-row sm:items-center sm:justify-between ${
                    isModelActive || isCurrentFormModel
                      ? "bg-zinc-50 dark:bg-zinc-800/60"
                      : "hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2 min-w-0 sm:flex-nowrap sm:gap-2.5">
                    <span className="font-mono text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
                      {m.name || m.id}
                    </span>

                    <div className="flex items-center gap-1.5 flex-wrap">
                      {m.tags.map((tag, idx) => (
                        <span
                          key={idx}
                          className="text-[10px] font-sans px-1.5 py-0.5 rounded-md bg-zinc-100 text-zinc-500 border border-zinc-200/60"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>

                    <span className="text-[11px] text-zinc-400">
                      {isModelActive
                        ? "当前"
                        : isCurrentFormModel
                        ? "已选择"
                        : m.model_type}
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 sm:shrink-0">
                    {/* Activating a saved model must not require re-fetching the
                        remote list: the pills above only render when fetchedModels
                        is non-empty, so without this there is no way to switch the
                        active model at all after a failed or offline fetch. */}
                    {!isModelActive && (
                      <button
                        type="button"
                        onClick={() => handleSelectModel(m.id, settingsTab)}
                        title={
                          settingsTab === "embedding"
                            ? "设为当前向量模型"
                            : "设为当前对话模型"
                        }
                        className="px-2.5 py-1 rounded-full text-[11px] border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:border-zinc-900 hover:text-zinc-900 dark:hover:border-zinc-100 dark:hover:text-zinc-100 transition-colors cursor-pointer"
                      >
                        使用
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleTestModel(m.id)}
                      disabled={isTesting}
                      title={
                        testState
                          ? testState.ok
                            ? `测试通过 · ${testState.latency_ms}ms`
                            : "测试失败"
                          : "测试模型响应与延迟"
                      }
                      className="p-1.5 rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                    >
                      <Zap
                        className={`w-3.5 h-3.5 ${
                          isTesting ? "animate-pulse text-amber-500" : ""
                        }`}
                      />
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setModelFormId(m.id);
                        setModelFormName(m.name || m.id);
                        setModelFormTags(m.tags.join(", "));
                        setEditingModelOriginalId(m.id);
                        setIsAddModelOpen(true);
                      }}
                      title="编辑模型"
                      className="p-1.5 rounded-full text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>

                    <button
                      type="button"
                      onClick={() =>
                        setDeleteConfirm({
                          type: "model",
                          id: m.id,
                          name: m.name || m.id,
                        })
                      }
                      title="删除模型"
                      className="p-1.5 rounded-full text-zinc-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors cursor-pointer"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Overall Connection Diagnostics */}
      {connectionDiagnostics && (
        <div
          className={`p-3 rounded-lg border text-xs flex items-center justify-between ${
            connectionDiagnostics.ok
              ? "bg-emerald-50/70 border-emerald-200 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
              : "bg-rose-50/70 border-rose-200 text-rose-800 dark:bg-rose-950/40 dark:border-rose-800 dark:text-rose-300"
          }`}
        >
          <div className="flex items-center gap-2">
            {connectionDiagnostics.ok ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
            )}
            <span>
              {connectionDiagnostics.ok
                ? `连接成功：往返延迟 ${connectionDiagnostics.latency_ms}ms`
                : `测试失败：${connectionDiagnostics.message}`}
            </span>
          </div>
          <button
            onClick={() => setConnectionDiagnostics(null)}
            className="text-zinc-400 hover:text-zinc-600 text-[11px] cursor-pointer"
          >
            关闭
          </button>
        </div>
      )}

      {/* Bottom Footer Actions */}
      <div className="flex items-center justify-end gap-2 pt-3">
        <PillButton
          variant="secondary"
          size="sm"
          onClick={handleTestConnection}
          disabled={testingConnection || !formBaseUrl}
          icon={
            testingConnection ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Activity className="w-3.5 h-3.5" />
            )
          }
        >
          {testingConnection ? "测试中..." : "测试"}
        </PillButton>

        <div className="flex items-center gap-2">
          {isCreatingNew ? (
            <>
              <PillButton
                variant="secondary"
                size="sm"
                onClick={handleCancelCreate}
              >
                取消
              </PillButton>
              <PillButton
                variant="primary"
                size="sm"
                onClick={handleSaveNewProvider}
                disabled={saving}
              >
                {saving ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                    创建中...
                  </>
                ) : (
                  "创建"
                )}
              </PillButton>
            </>
          ) : (
            <PillButton
              variant="primary"
              size="sm"
              onClick={handleSaveCurrentProvider}
              disabled={saving}
            >
              {saving ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                  保存中...
                </>
              ) : (
                "保存"
              )}
            </PillButton>
          )}
        </div>
      </div>
    </div>
  );
};

interface ProviderEmptyStateProps {
  ctrl: ProviderConfigCtrl;
}

/* VIEW C: Empty State */
export const ProviderEmptyState: React.FC<ProviderEmptyStateProps> = ({ ctrl }) => {
  const { handleStartCreate } = ctrl;

  return (
  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-400 gap-3">
    <Box className="w-12 h-12 text-zinc-300 dark:text-zinc-700" />
    <h3 className="text-base font-medium text-zinc-700 dark:text-zinc-300">
      未选择模型供应商
    </h3>
    <p className="text-xs text-zinc-400 max-w-sm">
      从左侧列表中选择一个供应商进行配置，或者点击“添加供应商”新建。
    </p>
    <PillButton
      variant="primary"
      size="sm"
      onClick={handleStartCreate}
      icon={<Plus className="w-3.5 h-3.5" />}
    >
      添加供应商
    </PillButton>
  </div>
  );
};
