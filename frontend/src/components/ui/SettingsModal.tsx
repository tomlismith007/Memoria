import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  Box,
  Check,
  CheckCircle2,
  ChevronDown,
  Cpu,
  Eye,
  EyeOff,
  Globe,
  Key,
  Layers,
  Link2,
  Loader2,
  MoreVertical,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Server,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { api } from "../../api";
import type {
  CustomModel,
  CustomProvider,
  ModelApiFormat,
  ProvidersConfigResponse,
} from "../../types";
import { PillButton } from "./PillButton";

const PROVIDERS_STORAGE_KEY = "memoria_custom_providers_cache";
const ACTIVE_PROVIDER_STORAGE_KEY = "memoria_active_provider_cache";
const ACTIVE_MODEL_STORAGE_KEY = "memoria_active_model_cache";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [providers, setProviders] = useState<CustomProvider[]>(() => {
    try {
      const cached = localStorage.getItem(PROVIDERS_STORAGE_KEY);
      return cached ? JSON.parse(cached) : [];
    } catch {
      return [];
    }
  });

  const [activeProviderId, setActiveProviderId] = useState<string>(() => {
    return localStorage.getItem(ACTIVE_PROVIDER_STORAGE_KEY) || "";
  });
  const [activeChatModel, setActiveChatModel] = useState<string>(() => {
    return localStorage.getItem(ACTIVE_MODEL_STORAGE_KEY) || "";
  });

  const [selectedProviderId, setSelectedProviderId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Detail panel form state
  const [formName, setFormName] = useState("");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formApiFormat, setFormApiFormat] = useState<ModelApiFormat>("chat_completions");
  const [formApiKey, setFormApiKey] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formChatModel, setFormChatModel] = useState("");
  const [formEmbedModel, setFormEmbedModel] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);

  // Model Fetching & Quick Selection State
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);
  const [modelSearchQuery, setModelSearchQuery] = useState("");
  const [showModelSelectionPanel, setShowModelSelectionPanel] = useState(false);

  // Inline Provider Creation State
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [draftModels, setDraftModels] = useState<CustomModel[]>([]);

  // New/Edit Model Modal
  const [isAddModelOpen, setIsAddModelOpen] = useState(false);
  const [modelFormId, setModelFormId] = useState("");
  const [modelFormName, setModelFormName] = useState("");
  const [modelFormTags, setModelFormTags] = useState("");
  const [editingModelOriginalId, setEditingModelOriginalId] = useState<string | null>(null);

  // Overall Connection test state
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionDiagnostics, setConnectionDiagnostics] = useState<{
    ok: boolean;
    latency_ms: number;
    message: string;
  } | null>(null);

  // Single model connectivity test state
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [modelTestResults, setModelTestResults] = useState<
    Record<string, { ok: boolean; latency_ms: number; message: string }>
  >({});

  // More menu popover
  const [showMoreMenu, setShowMoreMenu] = useState(false);

  const selectedProvider = providers.find((p) => p.id === selectedProviderId);

  // Sync to localStorage
  const syncToLocalStorage = (
    updatedProviders: CustomProvider[],
    updatedActiveId: string,
    updatedActiveModel: string
  ) => {
    try {
      localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(updatedProviders));
      localStorage.setItem(ACTIVE_PROVIDER_STORAGE_KEY, updatedActiveId);
      localStorage.setItem(ACTIVE_MODEL_STORAGE_KEY, updatedActiveModel);
    } catch (e) {
      console.warn("Failed to write to localStorage", e);
    }
  };

  // Populate form when selectedProvider changes
  useEffect(() => {
    if (selectedProvider && !isCreatingNew) {
      setFormName(selectedProvider.name);
      setFormBaseUrl(selectedProvider.base_url);
      setFormApiFormat(selectedProvider.api_format || "chat_completions");
      setFormApiKey("");
      setFormEnabled(selectedProvider.enabled);
      setShowApiKey(false);

      // Chat model: if active chat model belongs to this provider, use it; else first model
      const activeMatch = selectedProvider.models.find((m) => m.id === activeChatModel);
      setFormChatModel(activeMatch ? activeMatch.id : selectedProvider.models[0]?.id || "");
      setFormEmbedModel("");
      setFetchedModels([]);
      setShowModelSelectionPanel(false);
      setConnectionDiagnostics(null);
    }
  }, [selectedProviderId, isCreatingNew]);

  // Load from backend when modal opens
  const refreshProviders = async () => {
    setLoading(true);
    setFeedback(null);

    try {
      const data: ProvidersConfigResponse = await api.getProviders();
      if (data && Array.isArray(data.providers)) {
        if (data.providers.length > 0) {
          setProviders(data.providers);
          setActiveProviderId(data.active_provider_id);
          setActiveChatModel(data.active_chat_model);
          syncToLocalStorage(
            data.providers,
            data.active_provider_id,
            data.active_chat_model
          );
          if (!selectedProviderId || !data.providers.some((p) => p.id === selectedProviderId)) {
            const active = data.providers.find((p) => p.id === data.active_provider_id);
            setSelectedProviderId(active ? active.id : data.providers[0].id);
          }
        } else {
          // Check local cache
          const cachedStr = localStorage.getItem(PROVIDERS_STORAGE_KEY);
          if (cachedStr) {
            const cached: CustomProvider[] = JSON.parse(cachedStr);
            if (cached && cached.length > 0) {
              for (const p of cached) {
                await api.saveProvider({
                  id: p.id,
                  name: p.name,
                  base_url: p.base_url,
                  api_format: p.api_format,
                  api_key: p.api_key || "",
                  enabled: p.enabled,
                });
                for (const m of p.models) {
                  await api.saveProviderModel(p.id, m);
                }
              }
              const refreshed = await api.getProviders();
              setProviders(refreshed.providers);
              setActiveProviderId(refreshed.active_provider_id);
              setActiveChatModel(refreshed.active_chat_model);
              setSelectedProviderId(refreshed.providers[0]?.id || "");
            }
          }
        }
      }
    } catch (e) {
      console.error("Failed to load providers:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      refreshProviders();
    }
  }, [isOpen]);

  const showToast = (type: "success" | "error", text: string) => {
    setFeedback({ type, text });
    setTimeout(() => {
      setFeedback((prev) => (prev?.text === text ? null : prev));
    }, 3500);
  };

  // Start inline new provider creation
  const handleStartCreateProvider = () => {
    setIsCreatingNew(true);
    setSelectedProviderId("");
    setFormName("");
    setFormBaseUrl("https://");
    setFormApiKey("");
    setFormApiFormat("chat_completions");
    setFormChatModel("");
    setFormEmbedModel("");
    setFormEnabled(true);
    setFetchedModels([]);
    setShowModelSelectionPanel(false);
    setConnectionDiagnostics(null);
    setDraftModels([]);
    setShowApiKey(false);
  };

  // Cancel inline new provider creation
  const handleCancelCreate = () => {
    setIsCreatingNew(false);
    if (providers.length > 0) {
      setSelectedProviderId(providers[0].id);
    } else {
      setSelectedProviderId("");
    }
  };

  // 1. Fetch Models (获取模型)
  const handleFetchModels = async () => {
    const url = (formBaseUrl || selectedProvider?.base_url || "").trim();
    if (!url) {
      showToast("error", "请先输入 Base URL");
      return;
    }
    if (!url.startsWith("https://")) {
      showToast("error", "Base URL 必须是以 https:// 开头的合法公网地址");
      return;
    }
    setFetchingModels(true);
    setConnectionDiagnostics(null);
    try {
      const res = await api.fetchModels(
        url,
        formApiKey.trim(),
        formApiFormat
      );
      if (res.models && res.models.length > 0) {
        setFetchedModels(res.models);
        setShowModelSelectionPanel(true);
        if (!formChatModel.trim()) {
          setFormChatModel(res.models[0]);
        }
        if (isCreatingNew) {
          const autoDrafts: CustomModel[] = res.models.slice(0, 15).map((mId) => ({
            id: mId,
            name: mId,
            tags: [mId.includes("vision") || mId.includes("vl") ? "视觉" : "Chat"],
            enabled: true,
            model_type: "chat",
          }));
          setDraftModels(autoDrafts);
        }
        showToast("success", `成功获取 ${res.models.length} 个模型`);
      } else {
        showToast("error", "远端返回的模型列表为空");
      }
    } catch (e: any) {
      showToast("error", `获取模型失败: ${e.message}`);
    } finally {
      setFetchingModels(false);
    }
  };

  // 2. Select Model (选择模型)
  const handleSelectModel = async (modelId: string, modelType: "chat" | "embedding" = "chat") => {
    if (modelType === "chat") {
      setFormChatModel(modelId);
    } else {
      setFormEmbedModel(modelId);
    }

    if (isCreatingNew) {
      if (!draftModels.some((m) => m.id === modelId)) {
        setDraftModels((prev) => [
          ...prev,
          {
            id: modelId,
            name: modelId,
            tags: [modelId.includes("vision") || modelId.includes("vl") ? "视觉" : "Chat"],
            enabled: true,
            model_type: modelType,
          },
        ]);
      }
      showToast("success", `已选择对话模型: ${modelId}`);
      return;
    }

    if (!selectedProvider) return;

    // If model is not yet in provider's model list, automatically add it!
    const alreadyExists = selectedProvider.models.some((m) => m.id === modelId);
    if (!alreadyExists) {
      try {
        const defaultTag =
          modelId.includes("vision") || modelId.includes("vl")
            ? "视觉"
            : modelId.includes("embed")
            ? "Embedding"
            : "Chat";

        const res = await api.saveProviderModel(selectedProvider.id, {
          id: modelId,
          name: modelId,
          tags: [defaultTag],
          enabled: true,
          model_type: modelType,
        });

        const updated = providers.map((p) =>
          p.id === selectedProvider.id ? res.provider : p
        );
        setProviders(updated);
        syncToLocalStorage(updated, activeProviderId, modelId);
      } catch (err) {
        console.warn("Auto-adding model failed", err);
      }
    }

    // Activate this model
    try {
      const actRes = await api.activateProvider(selectedProvider.id, modelId);
      setActiveProviderId(actRes.active_provider_id);
      setActiveChatModel(actRes.active_chat_model);
      syncToLocalStorage(providers, actRes.active_provider_id, actRes.active_chat_model);
      showToast("success", `已选择并激活模型: ${modelId}`);
    } catch (err: any) {
      showToast("error", err.message || "切换激活模型失败");
    }
  };

  // Import all fetched models
  const handleImportAllFetched = async () => {
    if (fetchedModels.length === 0) return;
    if (isCreatingNew) {
      const added: CustomModel[] = fetchedModels.slice(0, 30).map((mId) => ({
        id: mId,
        name: mId,
        tags: [mId.includes("vision") || mId.includes("vl") ? "视觉" : "Chat"],
        enabled: true,
        model_type: "chat",
      }));
      setDraftModels(added);
      showToast("success", `已批量导入 ${added.length} 个模型`);
      return;
    }

    if (!selectedProvider) return;
    try {
      for (const mId of fetchedModels.slice(0, 30)) {
        if (!selectedProvider.models.some((m) => m.id === mId)) {
          await api.saveProviderModel(selectedProvider.id, {
            id: mId,
            name: mId,
            tags: [mId.includes("vision") ? "视觉" : "Chat"],
            enabled: true,
          });
        }
      }
      const refreshed = await api.getProviders();
      setProviders(refreshed.providers);
      syncToLocalStorage(refreshed.providers, activeProviderId, activeChatModel);
      showToast("success", `已批量导入模型至列表`);
    } catch (e: any) {
      showToast("error", e.message || "批量导入失败");
    }
  };

  // Save current provider changes (existing provider)
  const handleSaveCurrentProvider = async () => {
    if (!selectedProvider) return;
    if (!formName.trim()) {
      showToast("error", "供应商名称不能为空");
      return;
    }
    if (!formBaseUrl.trim() || !formBaseUrl.startsWith("https://")) {
      showToast("error", "Base URL 必须是以 https:// 开头的合法公网地址");
      return;
    }

    setSaving(true);
    try {
      const res = await api.saveProvider({
        id: selectedProvider.id,
        name: formName.trim(),
        base_url: formBaseUrl.trim(),
        api_format: formApiFormat,
        api_key: formApiKey.trim(),
        enabled: formEnabled,
        active_chat_model: formChatModel.trim(),
        active_embed_model: formEmbedModel.trim(),
      });

      const updated = providers.map((p) =>
        p.id === selectedProvider.id
          ? {
              ...p,
              name: formName.trim(),
              base_url: formBaseUrl.trim(),
              api_format: formApiFormat,
              enabled: formEnabled,
              api_key_set: formApiKey.trim() ? true : p.api_key_set,
              masked_api_key: res.provider.masked_api_key || p.masked_api_key,
            }
          : p
      );
      setProviders(updated);
      const nextActiveModel = formChatModel.trim() || activeChatModel;
      setActiveChatModel(nextActiveModel);
      syncToLocalStorage(updated, activeProviderId, nextActiveModel);
      setFormApiKey("");
      showToast("success", "供应商配置已成功保存并持久化");
    } catch (e: any) {
      showToast("error", e.message || "保存供应商失败");
    } finally {
      setSaving(false);
    }
  };

  // Save new provider (inline creation)
  const handleSaveNewProvider = async () => {
    const trimmedName = formName.trim();
    const trimmedUrl = formBaseUrl.trim();
    if (!trimmedName) {
      showToast("error", "请输入供应商名称");
      return;
    }
    if (!trimmedUrl || !trimmedUrl.startsWith("https://")) {
      showToast("error", "Base URL 必须是以 https:// 开头的合法公网地址");
      return;
    }

    const chosenModel =
      formChatModel.trim() ||
      (draftModels.length > 0 ? draftModels[0].id : "") ||
      (fetchedModels.length > 0 ? fetchedModels[0] : "");

    setSaving(true);
    try {
      const res = await api.saveProvider({
        name: trimmedName,
        base_url: trimmedUrl,
        api_format: formApiFormat,
        api_key: formApiKey.trim(),
        enabled: formEnabled,
        active_chat_model: chosenModel,
        active_embed_model: formEmbedModel.trim(),
      });

      const newP = res.provider;

      // Automatically add the selected chat model
      if (chosenModel && !draftModels.some((m) => m.id === chosenModel)) {
        await api.saveProviderModel(newP.id, {
          id: chosenModel,
          name: chosenModel,
          tags: [chosenModel.includes("vision") || chosenModel.includes("vl") ? "视觉" : "Chat"],
          enabled: true,
          model_type: "chat",
        });
      }

      // Also import all draft models
      for (const m of draftModels) {
        try {
          await api.saveProviderModel(newP.id, {
            id: m.id,
            name: m.name,
            tags: m.tags,
            enabled: m.enabled,
            model_type: m.model_type || "chat",
          });
        } catch {}
      }

      const refreshed = await api.getProviders();
      setProviders(refreshed.providers);
      setIsCreatingNew(false);
      setSelectedProviderId(newP.id);
      setActiveProviderId(newP.id);
      const activeModelToSet =
        chosenModel ||
        refreshed.active_chat_model ||
        (refreshed.providers.find((p) => p.id === newP.id)?.models[0]?.id || "");
      setActiveChatModel(activeModelToSet);
      syncToLocalStorage(refreshed.providers, newP.id, activeModelToSet);

      showToast("success", `供应商 ${newP.name} 创建成功并已生效`);
    } catch (e: any) {
      showToast("error", e.message || "创建供应商失败");
    } finally {
      setSaving(false);
    }
  };

  // Delete provider
  const handleDeleteProvider = async (providerId: string) => {
    const p = providers.find((item) => item.id === providerId);
    if (!p) return;
    if (!window.confirm(`确定删除供应商“${p.name}”及其全部模型配置吗？`)) return;

    try {
      const res = await api.deleteProvider(providerId);
      const remaining = res.providers;
      setProviders(remaining);
      let nextActive = activeProviderId === providerId ? "" : activeProviderId;
      let nextModel = activeProviderId === providerId ? "" : activeChatModel;
      if (activeProviderId === providerId && remaining.length > 0) {
        nextActive = remaining[0].id;
        nextModel = remaining[0].models[0]?.id || "";
      }
      setActiveProviderId(nextActive);
      setActiveChatModel(nextModel);
      setSelectedProviderId(remaining[0]?.id || "");
      syncToLocalStorage(remaining, nextActive, nextModel);
      showToast("success", `已删除供应商 ${p.name}`);
    } catch (e: any) {
      showToast("error", e.message || "删除供应商失败");
    }
  };

  // Overall Connection test
  const handleTestConnection = async () => {
    const url = (formBaseUrl || selectedProvider?.base_url || "").trim();
    if (!url || !url.startsWith("https://")) {
      showToast("error", "请先输入合法的 HTTPS Base URL");
      return;
    }

    setTestingConnection(true);
    setConnectionDiagnostics(null);
    try {
      let res: { llm_ok: boolean; llm_latency_ms: number; llm_message: string };
      if (selectedProvider && !isCreatingNew) {
        res = await api.testProvider(selectedProvider.id, formChatModel || undefined);
      } else {
        res = await api.testConfig({
          llm_base_url: url,
          llm_api_key: formApiKey.trim(),
          llm_model: formChatModel.trim() || "test",
          api_format: formApiFormat,
        });
      }
      setConnectionDiagnostics({
        ok: res.llm_ok,
        latency_ms: res.llm_latency_ms,
        message: res.llm_message,
      });
      if (res.llm_ok) {
        showToast("success", `连通性测试通过 (${res.llm_latency_ms}ms)`);
      } else {
        showToast("error", `连接失败: ${res.llm_message}`);
      }
    } catch (e: any) {
      setConnectionDiagnostics({
        ok: false,
        latency_ms: 0,
        message: e.message || "连通性测试失败",
      });
      showToast("error", e.message || "测试失败");
    } finally {
      setTestingConnection(false);
    }
  };

  // Test single model connectivity
  const handleTestModel = async (modelId: string) => {
    setTestingModelId(modelId);
    try {
      let res: { llm_ok: boolean; llm_latency_ms: number; llm_message: string };
      if (selectedProvider && !isCreatingNew) {
        res = await api.testProvider(selectedProvider.id, modelId);
      } else {
        res = await api.testConfig({
          llm_base_url: formBaseUrl.trim(),
          llm_api_key: formApiKey.trim(),
          llm_model: modelId,
          api_format: formApiFormat,
        });
      }
      setModelTestResults((prev) => ({
        ...prev,
        [modelId]: {
          ok: res.llm_ok,
          latency_ms: res.llm_latency_ms,
          message: res.llm_message,
        },
      }));
      if (res.llm_ok) {
        showToast("success", `${modelId} 连接成功: ${res.llm_latency_ms}ms`);
      } else {
        showToast("error", `${modelId} 连接失败: ${res.llm_message}`);
      }
    } catch (e: any) {
      setModelTestResults((prev) => ({
        ...prev,
        [modelId]: {
          ok: false,
          latency_ms: 0,
          message: e.message || "连接测试失败",
        },
      }));
      showToast("error", e.message || "测试失败");
    } finally {
      setTestingModelId(null);
    }
  };

  // Add / Edit Model manually
  const handleSaveModel = async () => {
    const modelId = modelFormId.trim();
    if (!modelId) {
      showToast("error", "请输入模型 ID");
      return;
    }

    const tags = modelFormTags
      .split(/[,，\s]+/)
      .map((t) => t.trim())
      .filter(Boolean);

    if (isCreatingNew) {
      const newModel: CustomModel = {
        id: modelId,
        name: modelFormName.trim() || modelId,
        tags: tags.length > 0 ? tags : ["Chat"],
        enabled: true,
        model_type: "chat",
      };
      setDraftModels((prev) => [
        ...prev.filter((m) => m.id !== (editingModelOriginalId || modelId)),
        newModel,
      ]);
      if (!formChatModel.trim()) {
        setFormChatModel(modelId);
      }
      setIsAddModelOpen(false);
      setModelFormId("");
      setModelFormName("");
      setModelFormTags("");
      setEditingModelOriginalId(null);
      showToast("success", `模型 ${modelId} 已添加`);
      return;
    }

    if (!selectedProvider) return;

    try {
      const res = await api.saveProviderModel(selectedProvider.id, {
        id: modelId,
        name: modelFormName.trim() || modelId,
        tags: tags,
        enabled: true,
        model_type: "chat",
      });

      const updatedProviders = providers.map((p) =>
        p.id === selectedProvider.id ? res.provider : p
      );
      setProviders(updatedProviders);
      syncToLocalStorage(updatedProviders, activeProviderId, activeChatModel || modelId);
      if (selectedProvider.id === activeProviderId && !activeChatModel) {
        setActiveChatModel(modelId);
        setFormChatModel(modelId);
      }
      setIsAddModelOpen(false);
      setModelFormId("");
      setModelFormName("");
      setModelFormTags("");
      setEditingModelOriginalId(null);
      showToast("success", `模型 ${modelId} 已保存`);
    } catch (e: any) {
      showToast("error", e.message || "保存模型失败");
    }
  };

  // Delete model
  const handleDeleteModel = async (modelId: string) => {
    if (isCreatingNew) {
      setDraftModels((prev) => prev.filter((m) => m.id !== modelId));
      if (formChatModel === modelId) {
        setFormChatModel(draftModels.find((m) => m.id !== modelId)?.id || "");
      }
      showToast("success", `已移除模型 ${modelId}`);
      return;
    }

    if (!selectedProvider) return;
    if (!window.confirm(`确认删除模型“${modelId}”？`)) return;

    try {
      const res = await api.deleteProviderModel(selectedProvider.id, modelId);
      const updatedProviders = providers.map((p) =>
        p.id === selectedProvider.id ? res.provider : p
      );
      setProviders(updatedProviders);
      let nextActiveModel = activeChatModel;
      if (activeChatModel === modelId) {
        nextActiveModel = res.provider.models[0]?.id || "";
        setActiveChatModel(nextActiveModel);
        setFormChatModel(nextActiveModel);
      }
      syncToLocalStorage(updatedProviders, activeProviderId, nextActiveModel);
      showToast("success", `已删除模型 ${modelId}`);
    } catch (e: any) {
      showToast("error", e.message || "删除模型失败");
    }
  };

  if (!isOpen) return null;

  const currentModelList = isCreatingNew
    ? draftModels
    : selectedProvider
    ? selectedProvider.models
    : [];

  // Filtered fetched models list
  const filteredFetchedModels = fetchedModels.filter((m) =>
    m.toLowerCase().includes(modelSearchQuery.toLowerCase().trim())
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="relative w-full max-w-5xl h-[700px] max-h-[94vh] flex flex-col bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-sm z-10">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                模型设置
              </h2>
              {feedback && (
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full flex items-center gap-1 animate-in fade-in ${
                    feedback.type === "success"
                      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800"
                      : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400 border border-red-200 dark:border-red-800"
                  }`}
                >
                  {feedback.type === "success" ? (
                    <CheckCircle2 className="w-3.5 h-3.5" />
                  ) : (
                    <AlertCircle className="w-3.5 h-3.5" />
                  )}
                  {feedback.text}
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              管理自定义模型供应商，获取与选择模型，配置后可在聊天时无缝使用。
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={refreshProviders}
              title="重新加载配置"
              className="p-1.5 text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={handleStartCreateProvider}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-200 rounded-lg shadow-sm transition-all cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              添加供应商
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Two-Column Body */}
        <div className="flex-1 flex min-h-0 divide-x divide-zinc-200 dark:divide-zinc-800 overflow-hidden">
          {/* Left Column: Custom Providers List Sidebar (~240px) */}
          <div className="w-60 shrink-0 flex flex-col bg-zinc-50/70 dark:bg-zinc-900/50 p-3">
            <div className="px-2 py-1 text-xs font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-2">
              自定义供应商
            </div>

            {loading && providers.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-zinc-400 gap-2">
                <Loader2 className="w-5 h-5 animate-spin" />
                <span className="text-xs">加载供应商...</span>
              </div>
            ) : providers.length === 0 && !isCreatingNew ? (
              <div className="flex-1 flex flex-col items-center justify-center p-4 text-center text-zinc-400 gap-2">
                <Box className="w-8 h-8 text-zinc-300 dark:text-zinc-700" />
                <p className="text-xs">暂无自定义供应商</p>
                <button
                  onClick={handleStartCreateProvider}
                  className="mt-2 text-xs text-zinc-800 dark:text-zinc-200 underline font-medium cursor-pointer"
                >
                  立即添加
                </button>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
                {providers.map((p) => {
                  const isSelected = !isCreatingNew && p.id === selectedProviderId;
                  const isActive = p.id === activeProviderId;
                  const isConfigured = Boolean(p.base_url) && p.enabled;

                  return (
                    <div
                      key={p.id}
                      onClick={() => {
                        setIsCreatingNew(false);
                        setSelectedProviderId(p.id);
                      }}
                      className={`group relative flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all ${
                        isSelected
                          ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium shadow-sm border border-zinc-200 dark:border-zinc-700"
                          : "hover:bg-zinc-100 dark:hover:bg-zinc-800/60 text-zinc-600 dark:text-zinc-400"
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Box
                          className={`w-4 h-4 shrink-0 transition-colors ${
                            isSelected
                              ? "text-zinc-900 dark:text-zinc-100"
                              : "text-zinc-400 dark:text-zinc-600"
                          }`}
                        />
                        <span className="text-sm truncate">{p.name}</span>
                        {isActive && (
                          <span className="shrink-0 text-[10px] px-1.5 py-0.2 rounded-full bg-zinc-100 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-300 font-normal">
                            当前
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          title={isConfigured ? "已启用" : "未就绪/已禁用"}
                          className={`w-2 h-2 rounded-full transition-colors ${
                            isConfigured
                              ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"
                              : "bg-zinc-300 dark:bg-zinc-600"
                          }`}
                        />
                      </div>
                    </div>
                  );
                })}

                {/* Draft item when creating new provider */}
                {isCreatingNew && (
                  <div className="group relative flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 font-medium shadow-sm border border-dashed border-zinc-400 dark:border-zinc-500">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <Plus className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0" />
                      <span className="text-sm truncate font-medium">
                        {formName.trim() || "新建供应商..."}
                      </span>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                      新建中
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right Column: Provider Details & Model Settings */}
          <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-zinc-900 overflow-y-auto">
            {(selectedProvider || isCreatingNew) ? (
              <div className="p-6 space-y-6">
                {/* Provider Header Toolbar */}
                <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800">
                  <div className="flex items-center gap-3 flex-1 min-w-0 mr-4">
                    <div className="w-10 h-10 rounded-xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-800 dark:text-zinc-200 shrink-0">
                      <Cpu className="w-5 h-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      {isCreatingNew ? (
                        <div>
                          <input
                            type="text"
                            value={formName}
                            onChange={(e) => setFormName(e.target.value)}
                            placeholder="输入供应商名称 (如: 商汤, stepfun, openrouter)"
                            className="w-full max-w-sm px-3 py-1.5 text-base font-semibold text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 transition-all"
                            autoFocus
                          />
                          <div className="text-[11px] text-zinc-400 mt-0.5 px-1">
                            新建自定义供应商 · 直接在此配置生效
                          </div>
                        </div>
                      ) : (
                        <>
                          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                            {formName || selectedProvider?.name}
                            {selectedProvider?.id === activeProviderId && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 font-normal">
                                当前激活
                              </span>
                            )}
                          </h3>
                          <span className="text-xs text-zinc-400 font-mono">
                            ID: {selectedProvider?.id}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    {/* Active Switch */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-zinc-500">
                        {formEnabled ? "已启用" : "已禁用"}
                      </span>
                      <button
                        type="button"
                        onClick={() => setFormEnabled(!formEnabled)}
                        className={`w-10 h-6 flex items-center rounded-full p-1 transition-colors duration-200 ease-in-out cursor-pointer ${
                          formEnabled ? "bg-emerald-500" : "bg-zinc-300 dark:bg-zinc-700"
                        }`}
                      >
                        <div
                          className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200 ease-in-out ${
                            formEnabled ? "translate-x-4" : "translate-x-0"
                          }`}
                        />
                      </button>
                    </div>

                    {isCreatingNew ? (
                      <button
                        type="button"
                        onClick={handleCancelCreate}
                        className="px-2.5 py-1 text-xs text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
                      >
                        取消
                      </button>
                    ) : (
                      <>
                        {selectedProvider?.id !== activeProviderId && (
                          <button
                            onClick={() =>
                              handleSelectModel(formChatModel || selectedProvider?.models[0]?.id || "")
                            }
                            className="px-2.5 py-1 text-xs border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
                          >
                            设为当前供应商
                          </button>
                        )}

                        {/* More Action Menu */}
                        <div className="relative">
                          <button
                            onClick={() => setShowMoreMenu(!showMoreMenu)}
                            className="p-1.5 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>

                          {showMoreMenu && (
                            <div
                              className="absolute right-0 mt-2 w-36 bg-white dark:bg-zinc-800 rounded-xl shadow-lg border border-zinc-200 dark:border-zinc-700 py-1 z-30 animate-in fade-in zoom-in-95"
                              onClick={() => setShowMoreMenu(false)}
                            >
                              <button
                                onClick={() => handleDeleteProvider(selectedProvider!.id)}
                                className="w-full text-left px-3 py-1.5 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 flex items-center gap-2 cursor-pointer"
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

                {/* Form Inputs: Base URL, Protocol, API Key */}
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
                      Base URL
                    </label>
                    <input
                      type="text"
                      value={formBaseUrl}
                      onChange={(e) => setFormBaseUrl(e.target.value)}
                      placeholder="https://api.openai.com/v1"
                      className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 font-mono"
                    />
                    <p className="text-[11px] text-zinc-400 mt-1">
                      API 根路径，要求 HTTPS/443（如 https://openrouter.ai/api/v1 或 https://api.deepseek.com/v1）
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
                        API 格式 (协议)
                      </label>
                      <select
                        value={formApiFormat}
                        onChange={(e) => setFormApiFormat(e.target.value as ModelApiFormat)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 transition-all"
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
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
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
                              : "输入 API Key (如 sk-...)"
                          }
                          className="w-full pl-3 pr-10 py-2 text-sm bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => setShowApiKey(!showApiKey)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
                        >
                          {showApiKey ? (
                            <EyeOff className="w-4 h-4" />
                          ) : (
                            <Eye className="w-4 h-4" />
                          )}
                        </button>
                      </div>
                      <p className="text-[11px] text-zinc-400 mt-1">
                        留空表示保留已有密钥；修改时输入新密钥自动替换。
                      </p>
                    </div>
                  </div>
                </div>

                {/* --- MODEL SELECTION & FETCHING SECTION (核心：模型的获取与选择) --- */}
                <div className="p-4 rounded-2xl bg-zinc-50/80 dark:bg-zinc-800/40 border border-zinc-200/90 dark:border-zinc-700/80 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Layers className="w-4 h-4 text-zinc-700 dark:text-zinc-300" />
                      <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                        模型选择与获取
                      </h4>
                    </div>

                    <button
                      type="button"
                      onClick={handleFetchModels}
                      disabled={fetchingModels || !formBaseUrl}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 hover:border-zinc-400 text-zinc-800 dark:text-zinc-200 rounded-xl shadow-xs transition-all cursor-pointer"
                      title="从供应商网关接口拉取全部可用模型"
                    >
                      <RefreshCw
                        className={`w-3.5 h-3.5 ${fetchingModels ? "animate-spin text-blue-600" : ""}`}
                      />
                      <span>{fetchingModels ? "正在获取模型..." : "获取模型"}</span>
                    </button>
                  </div>

                  {/* Input fields for Chat Model & Embedding Model */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                          当前对话模型 (Chat Model)
                        </label>
                        {formChatModel && (
                          <span className="text-[10px] font-mono text-emerald-600 dark:text-emerald-400">
                            已选择
                          </span>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={formChatModel}
                          onChange={(e) => setFormChatModel(e.target.value)}
                          placeholder="如 stealth/union-alpha, deepseek-chat"
                          className="flex-1 px-3 py-2 text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl font-mono focus:outline-none focus:ring-2 focus:ring-zinc-900/10"
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                          向量模型 (Embedding Model)
                        </label>
                        <span className="text-[10px] text-zinc-400">可选</span>
                      </div>
                      <input
                        type="text"
                        value={formEmbedModel}
                        onChange={(e) => setFormEmbedModel(e.target.value)}
                        placeholder="如 text-embedding-3-small (选填)"
                        className="w-full px-3 py-2 text-sm bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl font-mono focus:outline-none focus:ring-2 focus:ring-zinc-900/10"
                      />
                    </div>
                  </div>

                  {/* Quick Selectable Model Chips Area (展开的选择模型列表) */}
                  {(fetchedModels.length > 0 || currentModelList.length > 0) && (
                    <div className="pt-2 border-t border-zinc-200/60 dark:border-zinc-700/60 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                            选择模型
                          </span>
                          <span className="text-[11px] text-zinc-400">
                            (点击模型徽标直接设为当前对话模型)
                          </span>
                        </div>

                        {fetchedModels.length > 0 && (
                          <button
                            type="button"
                            onClick={handleImportAllFetched}
                            className="text-[11px] text-zinc-600 dark:text-zinc-300 hover:text-zinc-900 underline cursor-pointer"
                          >
                            全部添加到模型列表
                          </button>
                        )}
                      </div>

                      {/* Search / Filter if many models */}
                      {(fetchedModels.length > 10 || currentModelList.length > 10) && (
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

                      {/* Selectable Model Pills */}
                      <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto pt-1 pr-1">
                        {/* 1. Models already in provider */}
                        {currentModelList.map((m) => {
                          const isCurrent = formChatModel === m.id;
                          return (
                            <button
                              key={`p-${m.id}`}
                              type="button"
                              onClick={() => handleSelectModel(m.id, "chat")}
                              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono transition-all cursor-pointer ${
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

                        {/* 2. Fetched models that are not yet in provider */}
                        {filteredFetchedModels
                          .filter((fm) => !currentModelList.some((m) => m.id === fm))
                          .map((fm) => {
                            const isCurrent = formChatModel === fm;
                            return (
                              <button
                                key={`f-${fm}`}
                                type="button"
                                onClick={() => handleSelectModel(fm, "chat")}
                                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-mono transition-all cursor-pointer ${
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

                {/* Model List Section (管理模型列表) */}
                <div className="pt-2 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                        模型列表
                      </h4>
                      <span className="text-xs text-zinc-400 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded-full font-mono">
                        {currentModelList.length} 个模型
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={handleFetchModels}
                        disabled={fetchingModels || !formBaseUrl}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
                      >
                        <RefreshCw
                          className={`w-3.5 h-3.5 ${fetchingModels ? "animate-spin" : ""}`}
                        />
                        获取模型
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setModelFormId("");
                          setModelFormName("");
                          setModelFormTags("1M, 视觉");
                          setEditingModelOriginalId(null);
                          setIsAddModelOpen(true);
                        }}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-200 rounded-lg shadow-sm transition-colors cursor-pointer"
                      >
                        <Plus className="w-3.5 h-3.5" />
                        添加模型
                      </button>
                    </div>
                  </div>

                  {/* Models Table/Cards */}
                  {currentModelList.length === 0 ? (
                    <div className="py-8 border border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl flex flex-col items-center justify-center text-center text-zinc-400 gap-2">
                      <Layers className="w-6 h-6 text-zinc-300 dark:text-zinc-700" />
                      <p className="text-xs">该供应商尚未添加任何模型</p>
                      <p className="text-[11px] text-zinc-400">
                        点击上方「获取模型」自动拉取或「添加模型」手动创建
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {currentModelList.map((m) => {
                        const isModelActive =
                          !isCreatingNew &&
                          selectedProvider?.id === activeProviderId &&
                          activeChatModel === m.id;
                        const isCurrentFormModel = formChatModel === m.id;
                        const testState = modelTestResults[m.id];
                        const isTesting = testingModelId === m.id;

                        return (
                          <div
                            key={m.id}
                            className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl border transition-all ${
                              isModelActive || isCurrentFormModel
                                ? "bg-zinc-50/90 dark:bg-zinc-800/80 border-zinc-300 dark:border-zinc-600 shadow-xs"
                                : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 hover:border-zinc-300"
                            }`}
                          >
                            <div className="flex items-center gap-2.5 min-w-0">
                              <span className="font-mono text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
                                {m.name || m.id}
                              </span>

                              {/* Tags */}
                              <div className="flex items-center gap-1.5 flex-wrap">
                                {m.tags.map((tag, idx) => (
                                  <span
                                    key={idx}
                                    className="text-[11px] font-sans px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700"
                                  >
                                    {tag}
                                  </span>
                                ))}
                              </div>

                              {/* Active Badge */}
                              {isModelActive ? (
                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 font-sans font-medium">
                                  当前对话模型
                                </span>
                              ) : isCurrentFormModel ? (
                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-400 border border-blue-200 font-sans">
                                  已选定
                                </span>
                              ) : null}

                              {/* Test Result Indicator */}
                              {testState && (
                                <span
                                  className={`text-[11px] font-mono flex items-center gap-1 ${
                                    testState.ok
                                      ? "text-emerald-600 dark:text-emerald-400"
                                      : "text-red-500"
                                  }`}
                                  title={testState.message}
                                >
                                  {testState.ok ? (
                                    <>
                                      <Check className="w-3 h-3" />
                                      {testState.latency_ms}ms
                                    </>
                                  ) : (
                                    "测试失败"
                                  )}
                                </span>
                              )}
                            </div>

                            {/* Actions Right (matching screenshot tools: plug/test, pencil, trash, switch) */}
                            <div className="flex items-center gap-2 shrink-0">
                              {/* 设为当前使用 */}
                              {!isModelActive && (
                                <button
                                  type="button"
                                  onClick={() => handleSelectModel(m.id, "chat")}
                                  title="设为此模型对话"
                                  className="text-xs px-2 py-1 text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-md transition-colors font-medium"
                                >
                                  选择使用
                                </button>
                              )}

                              {/* Test Button (Plug / Zap) */}
                              <button
                                type="button"
                                onClick={() => handleTestModel(m.id)}
                                disabled={isTesting}
                                title="测试模型响应与网络延迟"
                                className="p-1.5 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
                              >
                                <Zap
                                  className={`w-3.5 h-3.5 ${
                                    isTesting ? "animate-pulse text-amber-500" : ""
                                  }`}
                                />
                              </button>

                              {/* Edit Button */}
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
                                className="p-1.5 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>

                              {/* Delete Button */}
                              <button
                                type="button"
                                onClick={() => handleDeleteModel(m.id)}
                                title="删除模型"
                                className="p-1.5 text-zinc-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg transition-colors cursor-pointer"
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
                    className={`p-3 rounded-xl border text-xs flex items-center justify-between ${
                      connectionDiagnostics.ok
                        ? "bg-emerald-50/70 border-emerald-200 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
                        : "bg-red-50/70 border-red-200 text-red-800 dark:bg-red-950/40 dark:border-red-800 dark:text-red-300"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      {connectionDiagnostics.ok ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                      ) : (
                        <AlertCircle className="w-4 h-4 text-red-600 shrink-0" />
                      )}
                      <span>
                        {connectionDiagnostics.ok
                          ? `连接成功：往返延迟 ${connectionDiagnostics.latency_ms}ms`
                          : `测试失败：${connectionDiagnostics.message}`}
                      </span>
                    </div>
                    <button
                      onClick={() => setConnectionDiagnostics(null)}
                      className="text-zinc-400 hover:text-zinc-600 text-[11px]"
                    >
                      关闭
                    </button>
                  </div>
                )}

                {/* Bottom Footer Actions */}
                <div className="flex items-center justify-between pt-4 border-t border-zinc-100 dark:border-zinc-800">
                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={testingConnection || !formBaseUrl}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {testingConnection ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Activity className="w-3.5 h-3.5" />
                    )}
                    <span>{testingConnection ? "测试连接中..." : "测试当前配置"}</span>
                  </button>

                  <div className="flex items-center gap-2">
                    {isCreatingNew ? (
                      <>
                        <button
                          type="button"
                          onClick={handleCancelCreate}
                          className="px-3.5 py-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-xl transition-colors cursor-pointer"
                        >
                          取消
                        </button>
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
                            "保存并生效供应商"
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
                          "保存配置并持久化"
                        )}
                      </PillButton>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-400 gap-3">
                <Box className="w-12 h-12 text-zinc-300 dark:text-zinc-700" />
                <h3 className="text-base font-medium text-zinc-700 dark:text-zinc-300">
                  未选择任何模型供应商
                </h3>
                <p className="text-xs text-zinc-400 max-w-sm">
                  从左侧列表中选择一个供应商进行配置，或者点击右上角“添加供应商”新建一个。
                </p>
                <button
                  onClick={handleStartCreateProvider}
                  className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 rounded-lg shadow-sm cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" />
                  新建供应商
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Modal: Add/Edit Model Dialog */}
        {isAddModelOpen && (
          <div className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in">
            <div
              className="w-full max-w-md bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl shadow-xl p-5 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                  {editingModelOriginalId ? "编辑模型" : "添加模型"}
                </h3>
                <button
                  onClick={() => setIsAddModelOpen(false)}
                  className="p-1 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
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
                    placeholder="如 stealth/union-alpha, deepseek-chat"
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
                    placeholder="如 Union Alpha 1M"
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
                    placeholder="如 1M, 视觉, 推理, Chat"
                    className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10"
                  />
                  <div className="flex gap-1.5 mt-2 flex-wrap">
                    {["128K", "1M", "视觉", "推理", "通用", "Embedding"].map((presetTag) => (
                      <button
                        key={presetTag}
                        type="button"
                        onClick={() => {
                          const current = modelFormTags
                            .split(/[,，\s]+/)
                            .map((t) => t.trim())
                            .filter(Boolean);
                          if (!current.includes(presetTag)) {
                            setModelFormTags([...current, presetTag].join(", "));
                          }
                        }}
                        className="text-[11px] px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
                      >
                        +{presetTag}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsAddModelOpen(false)}
                  className="px-3 py-1.5 text-xs text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors"
                >
                  取消
                </button>
                <PillButton variant="primary" size="sm" onClick={handleSaveModel}>
                  保存
                </PillButton>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
