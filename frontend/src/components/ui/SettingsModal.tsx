import React, { useEffect, useState } from "react";
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
import { DeleteConfirmDialog } from "../settings/DeleteConfirmDialog";
import { ProviderSidebar } from "../settings/ProviderSidebar";
import {
  ProviderTemplatePicker,
  type ProviderTemplate,
} from "../settings/ProviderTemplatePicker";

const PROVIDERS_STORAGE_KEY = "memoria_custom_providers_cache";
const ACTIVE_PROVIDER_STORAGE_KEY = "memoria_active_provider_cache";
const ACTIVE_MODEL_STORAGE_KEY = "memoria_active_model_cache";
const ACTIVE_EMBED_PROVIDER_STORAGE_KEY = "memoria_active_embed_provider_cache";
const ACTIVE_EMBED_MODEL_STORAGE_KEY = "memoria_active_embed_model_cache";

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
  const [activeEmbedProviderId, setActiveEmbedProviderId] = useState<string>(() => {
    return localStorage.getItem(ACTIVE_EMBED_PROVIDER_STORAGE_KEY) || "";
  });
  const [activeEmbedModel, setActiveEmbedModel] = useState<string>(() => {
    return localStorage.getItem(ACTIVE_EMBED_MODEL_STORAGE_KEY) || "";
  });

  const [settingsTab, setSettingsTab] = useState<"chat" | "embedding">("chat");
  const [selectedProviderId, setSelectedProviderId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Template Picker State (参考 ZCode ProviderTemplatePicker)
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);

  // Detail panel form state
  const [formName, setFormName] = useState("");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formApiFormat, setFormApiFormat] = useState<ModelApiFormat>("chat_completions");
  const [formApiKey, setFormApiKey] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formChatModel, setFormChatModel] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);

  // Model Fetching & Quick Selection State
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);
  const [modelSearchQuery, setModelSearchQuery] = useState("");

  // Inline Provider Creation State
  const [isCreatingNew, setIsCreatingNew] = useState(false);
  const [draftModels, setDraftModels] = useState<CustomModel[]>([]);

  // New/Edit Model Modal
  const [isAddModelOpen, setIsAddModelOpen] = useState(false);
  const [modelFormId, setModelFormId] = useState("");
  const [modelFormName, setModelFormName] = useState("");
  const [modelFormTags, setModelFormTags] = useState("");
  const [editingModelOriginalId, setEditingModelOriginalId] = useState<string | null>(null);

  // In-modal sleek Delete Confirmation (替代原生 window.confirm)
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: "provider" | "model";
    id: string;
    name: string;
  } | null>(null);

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
    updatedActiveModel: string,
    updatedEmbedProviderId: string = activeEmbedProviderId,
    updatedEmbedModel: string = activeEmbedModel
  ) => {
    try {
      localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(updatedProviders));
      localStorage.setItem(ACTIVE_PROVIDER_STORAGE_KEY, updatedActiveId);
      localStorage.setItem(ACTIVE_MODEL_STORAGE_KEY, updatedActiveModel);
      localStorage.setItem(ACTIVE_EMBED_PROVIDER_STORAGE_KEY, updatedEmbedProviderId);
      localStorage.setItem(ACTIVE_EMBED_MODEL_STORAGE_KEY, updatedEmbedModel);
    } catch (e) {
      console.warn("Failed to write to localStorage", e);
    }
  };

  // Populate form when selectedProvider changes
  useEffect(() => {
    if (selectedProvider && !isCreatingNew && !showTemplatePicker) {
      setFormName(selectedProvider.name);
      setFormBaseUrl(selectedProvider.base_url);
      setFormApiFormat(selectedProvider.api_format || "chat_completions");
      setFormApiKey("");
      setFormEnabled(selectedProvider.enabled);
      setShowApiKey(false);

      if (settingsTab === "chat") {
        const chatModels = selectedProvider.models.filter((m) => m.model_type === "chat");
        const activeMatch = chatModels.find((m) => m.id === activeChatModel);
        setFormChatModel(activeMatch ? activeMatch.id : chatModels[0]?.id || "");
      } else {
        const embeddingModels = selectedProvider.models.filter((m) => m.model_type === "embedding");
        const activeMatch = embeddingModels.find((m) => m.id === activeEmbedModel);
        setFormChatModel(activeMatch ? activeMatch.id : embeddingModels[0]?.id || "");
      }
      setFetchedModels([]);
      setConnectionDiagnostics(null);
    }
  }, [selectedProviderId, isCreatingNew, showTemplatePicker, settingsTab]);

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
          setActiveEmbedProviderId(data.active_embed_provider_id);
          setActiveEmbedModel(data.active_embed_model);
          syncToLocalStorage(
            data.providers,
            data.active_provider_id,
            data.active_chat_model,
            data.active_embed_provider_id,
            data.active_embed_model
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
              setActiveEmbedProviderId(refreshed.active_embed_provider_id);
              setActiveEmbedModel(refreshed.active_embed_model);
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

  // Open Template Picker
  const handleOpenTemplatePicker = () => {
    setShowTemplatePicker(true);
    setIsCreatingNew(false);
    setShowMoreMenu(false);
  };

  const handleSwitchSettingsTab = (tab: "chat" | "embedding") => {
    setSettingsTab(tab);
    setIsCreatingNew(false);
    setShowTemplatePicker(false);
    setShowMoreMenu(false);
    setFetchedModels([]);
    setConnectionDiagnostics(null);
    const activeId =
      tab === "embedding"
        ? activeEmbedProviderId || providers[0]?.id || ""
        : activeProviderId || providers[0]?.id || "";
    setSelectedProviderId(activeId);
  };

  // Select a template from picker
  const handleSelectTemplate = (template: ProviderTemplate | null) => {
    setShowTemplatePicker(false);
    setIsCreatingNew(true);
    setSelectedProviderId("");
    setConnectionDiagnostics(null);
    setShowApiKey(false);

    if (template) {
      setFormName(template.name);
      setFormBaseUrl(template.baseUrl);
      setFormApiFormat(template.apiFormat);
      setFormApiKey("");
      setFormEnabled(true);
      setFormChatModel(template.defaultChatModel);
      setDraftModels(template.suggestedModels);
      setFetchedModels([]);
      showToast("success", `已应用 ${template.name} 预设模板，请输入 API Key`);
    } else {
      // Pure Custom Provider
      setFormName("");
      setFormBaseUrl("https://");
      setFormApiFormat("chat_completions");
      setFormApiKey("");
      setFormEnabled(true);
      setFormChatModel("");
      setDraftModels([]);
      setFetchedModels([]);
    }
  };

  // Cancel creation
  const handleCancelCreate = () => {
    setIsCreatingNew(false);
    setShowTemplatePicker(false);
    if (providers.length > 0) {
      setSelectedProviderId(providers[0].id);
    } else {
      setSelectedProviderId("");
    }
  };

  // Switch Provider in sidebar with dirty check
  const handleSelectProvider = (id: string) => {
    if (isCreatingNew && (formName.trim() || formApiKey.trim() || (formBaseUrl && formBaseUrl !== "https://"))) {
      if (!window.confirm("当前新建的供应商草稿尚未保存，确定放弃并切换吗？")) {
        return;
      }
    }
    setIsCreatingNew(false);
    setShowTemplatePicker(false);
    setSelectedProviderId(id);
  };

  // 1. Fetch Remote Models (获取模型)
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
        settingsTab === "embedding" ? "chat_completions" : formApiFormat
      );
      if (res.models && res.models.length > 0) {
        setFetchedModels(res.models);
        if (!formChatModel.trim()) {
          setFormChatModel(res.models[0]);
        }
        if (isCreatingNew) {
          const autoDrafts: CustomModel[] = res.models.slice(0, 15).map((mId) => ({
            id: mId,
            name: mId,
            tags: [mId.includes("vision") || mId.includes("vl") ? "视觉" : "Chat"],
            enabled: true,
            model_type: settingsTab,
          }));
          setDraftModels(autoDrafts);
        }
        showToast("success", `成功拉取 ${res.models.length} 个可用模型`);
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
    setFormChatModel(modelId);

    if (isCreatingNew) {
      if (!draftModels.some((m) => m.id === modelId)) {
        setDraftModels((prev) => [
          ...prev,
          {
            id: modelId,
            name: modelId,
            tags: [
              modelId.includes("vision") || modelId.includes("vl")
                ? "视觉"
                : modelType === "embedding"
                ? "Embedding"
                : "Chat",
            ],
            enabled: true,
            model_type: modelType,
          },
        ]);
      }
      showToast("success", `已选择${modelType === "chat" ? "对话" : "向量"}模型: ${modelId}`);
      return;
    }

    if (!selectedProvider) return;

    // Auto-add model if not yet in provider list
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
      const actRes = await api.activateProvider(selectedProvider.id, modelId, modelType);
      if (modelType === "chat") {
        setActiveProviderId(actRes.active_provider_id);
        setActiveChatModel(actRes.active_chat_model);
        setProviders((prev) => {
          syncToLocalStorage(
            prev,
            actRes.active_provider_id,
            actRes.active_chat_model,
            actRes.active_embed_provider_id,
            actRes.active_embed_model
          );
          return prev;
        });
      } else {
        setActiveEmbedProviderId(actRes.active_embed_provider_id);
        setActiveEmbedModel(actRes.active_embed_model);
        setProviders((prev) => {
          syncToLocalStorage(
            prev,
            activeProviderId,
            activeChatModel,
            actRes.active_embed_provider_id,
            actRes.active_embed_model
          );
          return prev;
        });
      }
      showToast(
        "success",
        `已激活${modelType === "chat" ? "对话" : "向量"}模型: ${modelId}`
      );
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
        model_type: settingsTab,
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
            model_type: settingsTab,
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
        api_format: settingsTab === "embedding" ? "chat_completions" : formApiFormat,
        api_key: formApiKey.trim(),
        enabled: formEnabled,
        scope: settingsTab,
        active_chat_model: settingsTab === "chat" ? formChatModel.trim() : undefined,
      });

      const updated = providers.map((p) =>
        p.id === selectedProvider.id
          ? {
              ...p,
              name: formName.trim(),
              base_url: formBaseUrl.trim(),
              api_format: settingsTab === "embedding" ? "chat_completions" : formApiFormat,
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

    const isEmbedding = settingsTab === "embedding";
    const chosenModel =
      formChatModel.trim() ||
      (draftModels.length > 0 ? draftModels[0].id : "") ||
      (fetchedModels.length > 0 ? fetchedModels[0] : "");

    setSaving(true);
    try {
      const res = await api.saveProvider({
        name: trimmedName,
        base_url: trimmedUrl,
        api_format: isEmbedding ? "chat_completions" : formApiFormat,
        api_key: formApiKey.trim(),
        enabled: formEnabled,
        scope: settingsTab,
        active_chat_model: isEmbedding ? undefined : chosenModel,
      });

      const newP = res.provider;

      // Automatically add chosen model
      if (chosenModel && !draftModels.some((m) => m.id === chosenModel)) {
        await api.saveProviderModel(newP.id, {
          id: chosenModel,
          name: chosenModel,
          tags: [
            chosenModel.includes("vision") || chosenModel.includes("vl")
              ? "视觉"
              : isEmbedding
              ? "Embedding"
              : "Chat",
          ],
          enabled: true,
          model_type: settingsTab,
        });
      }

      // Import all draft models
      for (const m of draftModels) {
        try {
          await api.saveProviderModel(newP.id, {
            id: m.id,
            name: m.name,
            tags: m.tags,
            enabled: m.enabled,
            model_type: m.model_type || settingsTab,
          });
        } catch {}
      }

      if (isEmbedding && chosenModel) {
        await api.activateProvider(newP.id, chosenModel, "embedding");
      }

      const refreshed = await api.getProviders();
      setProviders(refreshed.providers);
      setIsCreatingNew(false);
      setSelectedProviderId(newP.id);

      if (isEmbedding) {
        setActiveEmbedProviderId(refreshed.active_embed_provider_id || newP.id);
        setActiveEmbedModel(
          chosenModel || refreshed.active_embed_model
        );
        syncToLocalStorage(
          refreshed.providers,
          activeProviderId,
          activeChatModel,
          refreshed.active_embed_provider_id || newP.id,
          chosenModel || refreshed.active_embed_model
        );
      } else {
        setActiveProviderId(newP.id);
        const activeModelToSet =
          chosenModel ||
          refreshed.active_chat_model ||
          (refreshed.providers.find((p) => p.id === newP.id)?.models[0]?.id || "");
        setActiveChatModel(activeModelToSet);
        syncToLocalStorage(
          refreshed.providers,
          newP.id,
          activeModelToSet,
          refreshed.active_embed_provider_id,
          refreshed.active_embed_model
        );
      }

      showToast("success", `供应商 ${newP.name} 创建成功并已生效`);
    } catch (e: any) {
      showToast("error", e.message || "创建供应商失败");
    } finally {
      setSaving(false);
    }
  };

  // Perform Delete confirmed
  const handleExecuteDelete = async () => {
    if (!deleteConfirm) return;
    const target = deleteConfirm;
    setDeleteConfirm(null);

    if (target.type === "provider") {
      try {
        const res = await api.deleteProvider(target.id);
        const remaining = res.providers;
        setProviders(remaining);
        let nextActive = activeProviderId === target.id ? "" : activeProviderId;
        let nextModel = activeProviderId === target.id ? "" : activeChatModel;
        if (activeProviderId === target.id && remaining.length > 0) {
          nextActive = remaining[0].id;
          nextModel = remaining[0].models[0]?.id || "";
        }
        setActiveProviderId(nextActive);
        setActiveChatModel(nextModel);
        let nextEmbedProviderId = activeEmbedProviderId;
        let nextEmbedModel = activeEmbedModel;
        if (activeEmbedProviderId === target.id) {
          nextEmbedProviderId = "";
          nextEmbedModel = "";
          setActiveEmbedProviderId(nextEmbedProviderId);
          setActiveEmbedModel(nextEmbedModel);
        }
        setSelectedProviderId(remaining[0]?.id || "");
        syncToLocalStorage(remaining, nextActive, nextModel, nextEmbedProviderId, nextEmbedModel);
        showToast("success", `已删除供应商 ${target.name}`);
      } catch (e: any) {
        showToast("error", e.message || "删除供应商失败");
      }
    } else {
      // Model delete
      if (isCreatingNew) {
        setDraftModels((prev) => prev.filter((m) => m.id !== target.id));
        if (formChatModel === target.id) {
          setFormChatModel(draftModels.find((m) => m.id !== target.id)?.id || "");
        }
        showToast("success", `已移除模型 ${target.id}`);
        return;
      }

      if (!selectedProvider) return;
      try {
        const res = await api.deleteProviderModel(selectedProvider.id, target.id);
        const updatedProviders = providers.map((p) =>
          p.id === selectedProvider.id ? res.provider : p
        );
        setProviders(updatedProviders);
        let nextActiveModel = activeChatModel;
        let nextEmbedProviderId = activeEmbedProviderId;
        let nextEmbedModel = activeEmbedModel;
        if (settingsTab === "chat" && activeChatModel === target.id) {
          nextActiveModel =
            res.provider.models.find((m) => m.enabled && m.model_type === "chat")?.id || "";
          setActiveChatModel(nextActiveModel);
          setFormChatModel(nextActiveModel);
        }
        if (
          settingsTab === "embedding" &&
          activeEmbedProviderId === selectedProvider.id &&
          activeEmbedModel === target.id
        ) {
          nextEmbedProviderId = selectedProvider.id;
          nextEmbedModel =
            res.provider.models.find((m) => m.enabled && m.model_type === "embedding")?.id || "";
          if (!nextEmbedModel) nextEmbedProviderId = "";
          setActiveEmbedProviderId(nextEmbedProviderId);
          setActiveEmbedModel(nextEmbedModel);
        }
        syncToLocalStorage(
          updatedProviders,
          activeProviderId,
          nextActiveModel,
          nextEmbedProviderId,
          nextEmbedModel
        );
        showToast("success", `已删除模型 ${target.id}`);
      } catch (e: any) {
        showToast("error", e.message || "删除模型失败");
      }
    }
  };

  // Overall Connection test (实时读取输入的 formApiKey，避免测旧密钥)
  const handleTestConnection = async () => {
    const url = (formBaseUrl || selectedProvider?.base_url || "").trim();
    if (!url || !url.startsWith("https://")) {
      showToast("error", "请先输入合法的 HTTPS Base URL");
      return;
    }

    setTestingConnection(true);
    setConnectionDiagnostics(null);
    try {
      let res: {
        llm_ok: boolean;
        llm_latency_ms: number;
        llm_message: string;
        embed_ok?: boolean;
        embed_latency_ms?: number;
        embed_message?: string;
      };
      // 若用户输入了新 Key，或者处于新建中，优先使用包含实时 Key 的 testConfig 测试
      if (formApiKey.trim() || isCreatingNew) {
        if (settingsTab === "embedding") {
          res = await api.testConfig({
            embed_base_url: url,
            embed_api_key: formApiKey.trim(),
            embed_model:
              formChatModel.trim() ||
              draftModels[0]?.id ||
              selectedProvider?.models[0]?.id ||
              "",
          });
        } else {
          res = await api.testConfig({
            llm_base_url: url,
            llm_api_key: formApiKey.trim(),
            llm_model: formChatModel.trim() || (draftModels[0]?.id || selectedProvider?.models[0]?.id || "gpt-4o-mini"),
            api_format: formApiFormat,
          });
        }
      } else if (selectedProvider) {
        res = await api.testProvider(selectedProvider.id, formChatModel || undefined, settingsTab);
      } else if (settingsTab === "embedding") {
        res = await api.testConfig({
          embed_base_url: url,
          embed_api_key: formApiKey.trim(),
          embed_model: formChatModel.trim() || "test",
        });
      } else {
        res = await api.testConfig({
          llm_base_url: url,
          llm_api_key: formApiKey.trim(),
          llm_model: formChatModel.trim() || "test",
          api_format: formApiFormat,
        });
      }
      const isEmbeddingTest = settingsTab === "embedding";
      const ok = isEmbeddingTest ? res.embed_ok === true : res.llm_ok;
      const latency = isEmbeddingTest ? res.embed_latency_ms || 0 : res.llm_latency_ms;
      const message = isEmbeddingTest ? res.embed_message || "" : res.llm_message;
      setConnectionDiagnostics({
        ok,
        latency_ms: latency,
        message,
      });
      if (ok) {
        showToast("success", `连通性测试通过 (${latency}ms)`);
      } else {
        showToast("error", `连接失败: ${message}`);
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

  // Test single model connectivity (同样优先使用实时 Key)
  const handleTestModel = async (modelId: string) => {
    setTestingModelId(modelId);
    try {
      let res: {
        llm_ok: boolean;
        llm_latency_ms: number;
        llm_message: string;
        embed_ok?: boolean;
        embed_latency_ms?: number;
        embed_message?: string;
      };
      if (formApiKey.trim() || isCreatingNew) {
        if (settingsTab === "embedding") {
          res = await api.testConfig({
            embed_base_url: formBaseUrl.trim() || selectedProvider?.base_url || "",
            embed_api_key: formApiKey.trim(),
            embed_model: modelId,
          });
        } else {
          res = await api.testConfig({
            llm_base_url: formBaseUrl.trim() || selectedProvider?.base_url || "",
            llm_api_key: formApiKey.trim(),
            llm_model: modelId,
            api_format: formApiFormat,
          });
        }
      } else if (selectedProvider) {
        res = await api.testProvider(selectedProvider.id, modelId, settingsTab);
      } else if (settingsTab === "embedding") {
        res = await api.testConfig({
          embed_base_url: formBaseUrl.trim(),
          embed_api_key: formApiKey.trim(),
          embed_model: modelId,
        });
      } else {
        res = await api.testConfig({
          llm_base_url: formBaseUrl.trim(),
          llm_api_key: formApiKey.trim(),
          llm_model: modelId,
          api_format: formApiFormat,
        });
      }
      const ok = settingsTab === "embedding" ? res.embed_ok === true : res.llm_ok;
      const latency = settingsTab === "embedding" ? res.embed_latency_ms || 0 : res.llm_latency_ms;
      const message = settingsTab === "embedding" ? res.embed_message || "" : res.llm_message;
      setModelTestResults((prev) => ({
        ...prev,
        [modelId]: {
          ok,
          latency_ms: latency,
          message,
        },
      }));
      if (ok) {
        showToast("success", `${modelId} 连接成功: ${latency}ms`);
      } else {
        showToast("error", `${modelId} 连接失败: ${message}`);
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
        tags: tags.length > 0 ? tags : settingsTab === "embedding" ? ["Embedding"] : ["Chat"],
        enabled: true,
        model_type: settingsTab,
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
        model_type: settingsTab,
      });

      const updatedProviders = providers.map((p) =>
        p.id === selectedProvider.id ? res.provider : p
      );
      setProviders(updatedProviders);
      if (settingsTab === "chat") {
        syncToLocalStorage(updatedProviders, activeProviderId, activeChatModel || modelId);
        if (selectedProvider.id === activeProviderId && !activeChatModel) {
          setActiveChatModel(modelId);
          setFormChatModel(modelId);
        }
      } else {
        syncToLocalStorage(
          updatedProviders,
          activeProviderId,
          activeChatModel,
          activeEmbedProviderId,
          activeEmbedModel || modelId
        );
        if (!activeEmbedModel) {
          setActiveEmbedModel(modelId);
          setFormChatModel(modelId);
        }
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

  if (!isOpen) return null;

  const allProviderModels = isCreatingNew
    ? draftModels
    : selectedProvider
    ? selectedProvider.models
    : [];

  const currentModelList = allProviderModels.filter(
    (m) => m.model_type === settingsTab
  );

  const filteredFetchedModels = fetchedModels.filter((m) =>
    m.toLowerCase().includes(modelSearchQuery.toLowerCase().trim())
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-zinc-900/40 backdrop-blur-xs animate-fade-in">
      <div
        className="relative w-full max-w-5xl h-[720px] max-h-[92vh] flex flex-col bg-white border border-zinc-200 rounded-2xl shadow-[0_24px_80px_rgba(24,24,27,0.16)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 sm:px-7 py-5 border-b border-zinc-200/80 bg-white z-10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl sm:text-2xl font-semibold text-zinc-950 tracking-[-0.02em]">
                模型设置
              </h2>
              <p className="hidden sm:block text-xs sm:text-sm text-zinc-500 mt-1.5">
                管理模型供应商，配置后可在聊天时选择使用。
              </p>
            </div>

            <div className="flex items-center gap-2">
              {feedback && (
                <span
                  className={`hidden sm:inline text-xs ${
                    feedback.type === "success" ? "text-emerald-600" : "text-rose-600"
                  }`}
                >
                  {feedback.text}
                </span>
              )}
              <button
                type="button"
                onClick={refreshProviders}
                title="重新加载配置"
                className="p-2 rounded-full text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              </button>
              <PillButton
                variant="primary"
                size="sm"
                onClick={handleOpenTemplatePicker}
                icon={<Plus className="w-3.5 h-3.5" />}
              >
                添加供应商
              </PillButton>
              <button
                type="button"
                onClick={onClose}
                title="关闭"
                className="p-2 rounded-full text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          <div className="mt-4 inline-flex items-center gap-1 rounded-full bg-zinc-100 p-1">
            {(["chat", "embedding"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => handleSwitchSettingsTab(tab)}
                className={`rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  settingsTab === tab
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-800"
                }`}
              >
                {tab === "chat" ? "对话模型" : "向量模型"}
              </button>
            ))}
          </div>
        </div>

        {/* Two-Column Body: Responsive (w-14 on mobile, md:w-56 on desktop) */}
        <div className="flex-1 flex min-h-0 divide-x divide-zinc-200/80 dark:divide-zinc-800 overflow-hidden">
          <ProviderSidebar
            providers={providers}
            loading={loading}
            isCreatingNew={isCreatingNew}
            showTemplatePicker={showTemplatePicker}
            selectedProviderId={selectedProviderId}
            activeProviderId={activeProviderId}
            formName={formName}
            onSelectProvider={handleSelectProvider}
            onOpenTemplatePicker={handleOpenTemplatePicker}
          />

          {/* Right Column: Template Picker OR Provider Details Form */}
          <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-zinc-900 overflow-y-auto">
            {/* VIEW A: Provider Template Picker (参考 ZCode ProviderTemplatePicker) */}
            {showTemplatePicker ? (
              <ProviderTemplatePicker
                onBack={() => {
                  setShowTemplatePicker(false);
                  if (providers.length > 0 && !selectedProviderId) {
                    setSelectedProviderId(providers[0].id);
                  }
                }}
                onSelect={handleSelectTemplate}
              />
            ) : selectedProvider || isCreatingNew ? (
              /* VIEW B: Provider Detail & Model Management Form */
              <div className="p-5 sm:p-8 space-y-7 animate-fade-in">
                {/* Provider Header Toolbar */}
                <div className="flex flex-col items-stretch gap-3 pb-4 border-b border-zinc-100 dark:border-zinc-800 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3 min-w-0 sm:flex-1 sm:mr-4">
                    <div className="w-9 h-9 rounded-lg border border-zinc-200 bg-white flex items-center justify-center text-zinc-700 shrink-0 font-semibold text-xs">
                      {formName.trim().slice(0, 2).toUpperCase() || <Cpu className="w-5 h-5" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      {isCreatingNew ? (
                        <div>
                          <input
                            type="text"
                            value={formName}
                            onChange={(e) => setFormName(e.target.value)}
                            placeholder="输入供应商名称 (如: DeepSeek, SiliconFlow)"
                            className="w-full max-w-sm px-3 py-1.5 text-base font-semibold text-zinc-900 dark:text-zinc-100 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900/10 transition-all"
                            autoFocus
                          />
                          <div className="text-[11px] text-zinc-400 mt-0.5 px-0.5 flex flex-wrap items-center gap-2">
                            <span>新建供应商草稿</span>
                            <button
                              type="button"
                              onClick={handleOpenTemplatePicker}
                              className="text-zinc-600 dark:text-zinc-300 underline cursor-pointer hover:text-zinc-900"
                            >
                              重新选择模板
                            </button>
                          </div>
                        </div>
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

                <div className="space-y-5 max-w-2xl">
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
                    <p className="text-[11px] text-zinc-400 mt-1.5">留空保留已有密钥。</p>
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
                          {fetchedModels.length > 0 ? "可用模型" : "已添加模型"}
                        </span>

                        {fetchedModels.length > 0 && (
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
                <div className="space-y-2">

                  {currentModelList.length === 0 ? (
                    <div className="py-6 border border-dashed border-zinc-200 rounded-xl flex flex-col items-center justify-center text-center text-zinc-400 gap-1.5">
                      <Layers className="w-5 h-5 text-zinc-300" />
                      <p className="text-xs">暂无模型</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
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
                            className={`flex flex-col items-stretch gap-2 px-3.5 py-2.5 rounded-2xl border transition-all sm:flex-row sm:items-center sm:justify-between ${
                              isModelActive || isCurrentFormModel
                                ? "bg-zinc-50/90 dark:bg-zinc-800/80 border-zinc-300 dark:border-zinc-600 shadow-xs"
                                : "bg-white dark:bg-zinc-900 border-zinc-200/90 dark:border-zinc-800 hover:border-zinc-300"
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
                              {!isModelActive && (
                                <button
                                  type="button"
                                  onClick={() => handleSelectModel(m.id, settingsTab)}
                                  className="text-xs px-2.5 py-1 rounded-full text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors font-medium cursor-pointer"
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
                    className={`p-3 rounded-2xl border text-xs flex items-center justify-between ${
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
                <div className="flex items-center justify-end gap-2 pt-5 border-t border-zinc-100">
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
            ) : (
              /* VIEW C: Empty State */
              <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-400 gap-3">
                <Box className="w-12 h-12 text-zinc-300 dark:text-zinc-700" />
                <h3 className="text-base font-medium text-zinc-700 dark:text-zinc-300">
                  未选择模型供应商
                </h3>
                <p className="text-xs text-zinc-400 max-w-sm">
                  从左侧列表中选择一个供应商进行配置，或者点击“添加供应商”通过模板新建。
                </p>
                <PillButton
                  variant="primary"
                  size="sm"
                  onClick={handleOpenTemplatePicker}
                  icon={<Plus className="w-3.5 h-3.5" />}
                >
                  添加供应商
                </PillButton>
              </div>
            )}
          </div>
        </div>

        {/* Modal: Add/Edit Model Dialog */}
        {isAddModelOpen && (
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
                          const current = modelFormTags
                            .split(/[,，\s]+/)
                            .map((t) => t.trim())
                            .filter(Boolean);
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
        )}

        <DeleteConfirmDialog
          target={deleteConfirm}
          onCancel={() => setDeleteConfirm(null)}
          onConfirm={handleExecuteDelete}
        />
      </div>
    </div>
  );
};

export default SettingsModal;
