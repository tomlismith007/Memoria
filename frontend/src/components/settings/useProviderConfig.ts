import { useEffect, useState } from "react";
import { api } from "../../api";
import type {
  CustomModel,
  CustomProvider,
  ModelApiFormat,
  ProvidersConfigResponse,
} from "../../types";
import type { DeleteConfirmTarget } from "./DeleteConfirmDialog";

export const isEmbeddingModelId = (modelId: string): boolean => {
  const lower = modelId.toLowerCase();
  return (
    lower.includes("embed") ||
    lower.includes("bge") ||
    lower.includes("text-embedding") ||
    lower.includes("bert") ||
    lower.includes("rerank")
  );
};

export const deriveModelType = (
  modelId: string,
  fallback: "chat" | "embedding" = "chat"
): "chat" | "embedding" => {
  const lower = modelId.toLowerCase();
  if (isEmbeddingModelId(modelId)) return "embedding";
  if (
    lower.includes("gpt") ||
    lower.includes("claude") ||
    lower.includes("deepseek") ||
    lower.includes("qwen") ||
    lower.includes("llama") ||
    lower.includes("chat") ||
    lower.includes("instruct") ||
    lower.includes("glm")
  ) {
    return "chat";
  }
  return fallback;
};

// Single source of truth for model tags.
export const deriveTag = (modelId: string, embedding = false): string => {
  const lower = modelId.toLowerCase();
  if (lower.includes("vision") || lower.includes("vl")) return "视觉";
  if (embedding || isEmbeddingModelId(modelId)) return "Embedding";
  return "Chat";
};

export const splitTags = (raw: string): string[] =>
  raw
    .split(/[,，\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);

// Anonymous return type of api.testProvider / api.testConfig, which both
// declare it inline; named once here so the test flow can annotate it.
type ConnectivityResult = {
  llm_ok: boolean;
  llm_latency_ms: number;
  llm_message: string;
  embed_ok?: boolean;
  embed_latency_ms?: number;
  embed_message?: string;
};

// All provider/model configuration state and actions for the settings modal.
// Plain hook: no store, no reducer, no context. The backend
// (GET /api/config/providers) is the single source of truth — no local mirror.
export const useProviderConfig = (isOpen: boolean) => {
  const [providers, setProviders] = useState<CustomProvider[]>([]);
  const [activeProviderId, setActiveProviderId] = useState("");
  const [activeChatModel, setActiveChatModel] = useState("");
  const [activeEmbedProviderId, setActiveEmbedProviderId] = useState("");
  const [activeEmbedModel, setActiveEmbedModel] = useState("");

  const [settingsTab, setSettingsTab] = useState<"chat" | "embedding">("chat");
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
  const [modelFormType, setModelFormType] = useState<"chat" | "embedding">("chat");
  const [editingModelOriginalId, setEditingModelOriginalId] = useState<string | null>(null);

  // In-modal sleek Delete Confirmation (替代原生 window.confirm)
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmTarget | null>(null);

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

  // Populate form when selectedProvider changes
  useEffect(() => {
    if (selectedProvider && !isCreatingNew) {
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
  }, [selectedProviderId, isCreatingNew, settingsTab]);

  // Load from backend when modal opens
  const refreshProviders = async () => {
    setLoading(true);
    setFeedback(null);

    try {
      const data: ProvidersConfigResponse = await api.getProviders();
      if (data && Array.isArray(data.providers)) {
        setProviders(data.providers);
        setActiveProviderId(data.active_provider_id);
        setActiveChatModel(data.active_chat_model);
        setActiveEmbedProviderId(data.active_embed_provider_id);
        setActiveEmbedModel(data.active_embed_model);
        if (!selectedProviderId || !data.providers.some((p) => p.id === selectedProviderId)) {
          const active = data.providers.find((p) => p.id === data.active_provider_id);
          setSelectedProviderId(active ? active.id : data.providers[0]?.id || "");
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

  // Start creating a blank custom provider
  const handleStartCreate = () => {
    setIsCreatingNew(true);
    setSelectedProviderId("");
    setConnectionDiagnostics(null);
    setShowApiKey(false);
    setShowMoreMenu(false);
    setFormName("");
    setFormBaseUrl("https://");
    setFormApiFormat("chat_completions");
    setFormApiKey("");
    setFormEnabled(true);
    setFormChatModel("");
    setDraftModels([]);
    setFetchedModels([]);
  };

  const handleSwitchSettingsTab = (tab: "chat" | "embedding") => {
    setSettingsTab(tab);
    setIsCreatingNew(false);
    setShowMoreMenu(false);
    setFetchedModels([]);
    setConnectionDiagnostics(null);
    const activeId =
      tab === "embedding"
        ? activeEmbedProviderId || providers[0]?.id || ""
        : activeProviderId || providers[0]?.id || "";
    setSelectedProviderId(activeId);
  };

  // Cancel creation
  const handleCancelCreate = () => {
    setIsCreatingNew(false);
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
    setSelectedProviderId(id);
  };

  // The HTTPS Base URL rule, previously written 4 times under 3 wordings.
  const requireHttpsUrl = (raw: string): string | null => {
    const url = raw.trim();
    if (!url || !url.startsWith("https://")) {
      showToast("error", "Base URL 必须是以 https:// 开头的合法公网地址");
      return null;
    }
    return url;
  };

  // 1. Fetch Remote Models (获取模型)
  const handleFetchModels = async () => {
    const url = requireHttpsUrl(formBaseUrl || selectedProvider?.base_url || "");
    if (!url) return;
    setFetchingModels(true);
    setConnectionDiagnostics(null);
    try {
      const res = await api.fetchModels(
        url,
        formApiKey.trim(),
        settingsTab === "embedding" ? "chat_completions" : formApiFormat,
        // The browser only holds the masked key; the server resolves the stored
        // credential for this provider when the typed one is empty.
        isCreatingNew ? "" : selectedProvider?.id
      );
      if (res.models && res.models.length > 0) {
        setFetchedModels(res.models);
        if (!formChatModel.trim()) {
          setFormChatModel(res.models[0]);
        }
        if (isCreatingNew) {
          const autoDrafts: CustomModel[] = res.models.slice(0, 15).map((mId) => {
            const inferredType = deriveModelType(mId, settingsTab);
            return {
              id: mId,
              name: mId,
              tags: [deriveTag(mId, inferredType === "embedding")],
              enabled: true,
              model_type: inferredType,
            };
          });
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
            tags: [deriveTag(modelId, modelType === "embedding")],
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
        const defaultTag = deriveTag(modelId);

        const res = await api.saveProviderModel(selectedProvider.id, {
          id: modelId,
          name: modelId,
          tags: [defaultTag],
          enabled: true,
          model_type: modelType,
        });

        setProviders((prev) =>
          prev.map((p) => (p.id === selectedProvider.id ? res.provider : p))
        );
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
      } else {
        setActiveEmbedProviderId(actRes.active_embed_provider_id);
        setActiveEmbedModel(actRes.active_embed_model);
      }
      showToast(
        "success",
        `已激活${modelType === "chat" ? "对话" : "向量"}模型: ${modelId}`
      );
    } catch (err: any) {
      showToast("error", err.message || "切换激活模型失败");
    }
  };

  // Add a fetched model to the provider's list WITHOUT activating it. Pill
  // clicks used to route through handleSelectModel, which silently activated
  // embedding models as chat and corrupted the config (user report). Re-saving
  // an id with the current tab's type also repairs entries stored under the
  // wrong type.
  const handleAddFetchedModel = async (modelId: string) => {
    if (!selectedProvider) return;
    const existing = selectedProvider.models.find((m) => m.id === modelId);
    try {
      const res = await api.saveProviderModel(selectedProvider.id, {
        id: modelId,
        name: modelId,
        tags: [deriveTag(modelId, settingsTab === "embedding")],
        enabled: true,
        model_type: settingsTab,
      });
      setProviders((prev) =>
        prev.map((p) => (p.id === selectedProvider.id ? res.provider : p))
      );
      showToast(
        "success",
        !existing
          ? `已添加模型 ${modelId}`
          : existing.model_type === settingsTab
          ? `模型 ${modelId} 已在列表中`
          : `模型 ${modelId} 类型已更正为${settingsTab === "chat" ? "对话" : "向量"}模型`
      );
    } catch (e: any) {
      showToast("error", e.message || "添加模型失败");
    }
  };

  // Import all fetched models
  const handleImportAllFetched = async () => {
    if (fetchedModels.length === 0) return;
    if (isCreatingNew) {
      const added: CustomModel[] = fetchedModels.slice(0, 30).map((mId) => {
        const inferredType = deriveModelType(mId, settingsTab);
        return {
          id: mId,
          name: mId,
          tags: [deriveTag(mId, inferredType === "embedding")],
          enabled: true,
          model_type: inferredType,
        };
      });
      setDraftModels(added);
      showToast("success", `已批量导入 ${added.length} 个模型`);
      return;
    }

    if (!selectedProvider) return;
    try {
      const pending = fetchedModels
        .slice(0, 30)
        .filter((mId) => !selectedProvider.models.some((m) => m.id === mId));
      if (pending.length === 0) {
        showToast("success", "所有模型均已添加");
        return;
      }
      const modelsToSave = pending.map((mId) => {
        const inferredType = deriveModelType(mId, settingsTab);
        return {
          id: mId,
          name: mId,
          tags: [deriveTag(mId, inferredType === "embedding")],
          enabled: true,
          model_type: inferredType,
        };
      });

      await api.saveProviderModelsBatch(selectedProvider.id, modelsToSave);
      const refreshed = await api.getProviders();
      setProviders(refreshed.providers);
      // Say what actually changed:
      showToast("success", `已添加 ${modelsToSave.length} 个模型`);
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
    if (!requireHttpsUrl(formBaseUrl)) return;

    setSaving(true);
    try {
      const res = await api.saveProvider({
        id: selectedProvider.id,
        name: formName.trim(),
        base_url: formBaseUrl.trim(),
        api_format: settingsTab === "embedding" ? (selectedProvider.api_format || "chat_completions") : formApiFormat,
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
              api_format: settingsTab === "embedding" ? (selectedProvider.api_format || "chat_completions") : formApiFormat,
              enabled: formEnabled,
              api_key_set: formApiKey.trim() ? true : p.api_key_set,
              masked_api_key: res.provider.masked_api_key || p.masked_api_key,
            }
          : p
      );
      setProviders(updated);
      setActiveChatModel(formChatModel.trim() || activeChatModel);
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
    if (!requireHttpsUrl(trimmedUrl)) return;

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
        api_format: formApiFormat,
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
          tags: [deriveTag(chosenModel, isEmbedding)],
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
      } else if (!isEmbedding && chosenModel) {
        await api.activateProvider(newP.id, chosenModel, "chat");
      }

      const refreshed = await api.getProviders();
      setProviders(refreshed.providers);
      setIsCreatingNew(false);
      setSelectedProviderId(newP.id);

      if (isEmbedding) {
        setActiveEmbedProviderId(refreshed.active_embed_provider_id || newP.id);
        setActiveEmbedModel(refreshed.active_embed_model || chosenModel);
      } else {
        setActiveProviderId(refreshed.active_provider_id || newP.id);
        setActiveChatModel(
          refreshed.active_chat_model ||
            chosenModel ||
            (refreshed.providers.find((p) => p.id === newP.id)?.models[0]?.id || "")
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
        if (activeProviderId === target.id) {
          const next = remaining[0];
          setActiveProviderId(next?.id || "");
          setActiveChatModel(
            next?.models.find((m) => m.enabled && m.model_type === "chat")?.id || ""
          );
        }
        if (activeEmbedProviderId === target.id) {
          setActiveEmbedProviderId("");
          setActiveEmbedModel("");
        }
        setSelectedProviderId(remaining[0]?.id || "");
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
        setProviders((prev) =>
          prev.map((p) => (p.id === selectedProvider.id ? res.provider : p))
        );
        if (settingsTab === "chat" && activeChatModel === target.id) {
          const nextModel =
            res.provider.models.find((m) => m.enabled && m.model_type === "chat")?.id || "";
          setActiveChatModel(nextModel);
          setFormChatModel(nextModel);
        }
        if (
          settingsTab === "embedding" &&
          activeEmbedProviderId === selectedProvider.id &&
          activeEmbedModel === target.id
        ) {
          const nextModel =
            res.provider.models.find((m) => m.enabled && m.model_type === "embedding")?.id || "";
          setActiveEmbedProviderId(nextModel ? selectedProvider.id : "");
          setActiveEmbedModel(nextModel);
        }
        showToast("success", `已删除模型 ${target.id}`);
      } catch (e: any) {
        showToast("error", e.message || "删除模型失败");
      }
    }
  };

  // Connectivity test, merged from handleTestConnection + handleTestModel.
  // The two were near-verbatim copies of the same 4-way dispatch, each carrying
  // an identical inline result type and 2 branches that could never run: both
  // call sites render only under `selectedProvider || isCreatingNew`, so the
  // first branch failing forces the second. modelId omitted => overall test.
  const runConnectionTest = async (modelId?: string) => {
    const isPerModel = modelId !== undefined;
    const targetModel = modelId ?? "";
    const url = (formBaseUrl || selectedProvider?.base_url || "").trim();

    // Per-model runs skip the guard: they only re-probe a model already listed
    // under this provider, so the URL is known-good.
    if (!isPerModel && !requireHttpsUrl(url)) return;

    if (isPerModel) {
      setTestingModelId(targetModel);
    } else {
      setTestingConnection(true);
      setConnectionDiagnostics(null);
    }

    // 若用户输入了新 Key，或者处于新建中，优先使用包含实时 Key 的 testConfig 测试
    const probeModel = isPerModel
      ? targetModel
      : formChatModel.trim() ||
        draftModels[0]?.id ||
        selectedProvider?.models[0]?.id ||
        (settingsTab === "embedding" ? "" : "gpt-4o-mini");

    try {
      let res: ConnectivityResult;
      if (formApiKey.trim() || isCreatingNew) {
        res =
          settingsTab === "embedding"
            ? await api.testConfig({
                embed_base_url: url,
                embed_api_key: formApiKey.trim(),
                embed_model: probeModel,
              })
            : await api.testConfig({
                llm_base_url: url,
                llm_api_key: formApiKey.trim(),
                llm_model: probeModel,
                api_format: formApiFormat,
              });
      } else if (selectedProvider) {
        res = await api.testProvider(
          selectedProvider.id,
          isPerModel ? targetModel : formChatModel || undefined,
          settingsTab
        );
      } else {
        return; // unreachable: both call sites guarantee the branch above
      }

      const embedding = settingsTab === "embedding";
      const ok = embedding ? res.embed_ok === true : res.llm_ok;
      const latency = embedding ? res.embed_latency_ms || 0 : res.llm_latency_ms;
      const message = embedding ? res.embed_message || "" : res.llm_message;
      const outcome = { ok, latency_ms: latency, message };

      if (isPerModel) {
        setModelTestResults((prev) => ({ ...prev, [targetModel]: outcome }));
      } else {
        setConnectionDiagnostics(outcome);
      }

      if (ok) {
        showToast(
          "success",
          isPerModel ? `${targetModel} 连接成功: ${latency}ms` : `连通性测试通过 (${latency}ms)`
        );
      } else {
        showToast(
          "error",
          isPerModel ? `${targetModel} 连接失败: ${message}` : `连接失败: ${message}`
        );
      }
    } catch (e: any) {
      const outcome = { ok: false, latency_ms: 0, message: e.message || "连通性测试失败" };
      if (isPerModel) {
        setModelTestResults((prev) => ({ ...prev, [targetModel]: outcome }));
      } else {
        setConnectionDiagnostics(outcome);
      }
      showToast("error", e.message || "测试失败");
    } finally {
      if (isPerModel) {
        setTestingModelId(null);
      } else {
        setTestingConnection(false);
      }
    }
  };

  const handleTestConnection = () => runConnectionTest();
  const handleTestModel = (modelId: string) => runConnectionTest(modelId);

  const resetModelForm = () => {
    setIsAddModelOpen(false);
    setModelFormId("");
    setModelFormName("");
    setModelFormTags("");
    setModelFormType(settingsTab);
    setEditingModelOriginalId(null);
  };

  // Add / Edit Model manually
  const handleSaveModel = async () => {
    const modelId = modelFormId.trim();
    if (!modelId) {
      showToast("error", "请输入模型 ID");
      return;
    }

    const tags = splitTags(modelFormTags);

    if (isCreatingNew) {
      const newModel: CustomModel = {
        id: modelId,
        name: modelFormName.trim() || modelId,
        tags: tags.length > 0 ? tags : modelFormType === "embedding" ? ["Embedding"] : ["Chat"],
        enabled: true,
        model_type: modelFormType,
      };
      setDraftModels((prev) => [
        ...prev.filter((m) => m.id !== (editingModelOriginalId || modelId)),
        newModel,
      ]);
      if (!formChatModel.trim()) {
        setFormChatModel(modelId);
      }
      resetModelForm();
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
        model_type: modelFormType,
      });

      setProviders((prev) =>
        prev.map((p) => (p.id === selectedProvider.id ? res.provider : p))
      );
      if (settingsTab === "chat") {
        if (selectedProvider.id === activeProviderId && !activeChatModel) {
          setActiveChatModel(modelId);
          setFormChatModel(modelId);
        }
      } else if (!activeEmbedModel) {
        setActiveEmbedModel(modelId);
        setFormChatModel(modelId);
      }
      resetModelForm();
      showToast("success", `模型 ${modelId} 已保存`);
    } catch (e: any) {
      showToast("error", e.message || "保存模型失败");
    }
  };

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

  return {
    // state
    providers,
    activeProviderId,
    activeChatModel,
    activeEmbedProviderId,
    activeEmbedModel,
    settingsTab,
    selectedProviderId,
    loading,
    saving,
    feedback,
    formName,
    formBaseUrl,
    formApiFormat,
    formApiKey,
    formEnabled,
    formChatModel,
    showApiKey,
    fetchingModels,
    fetchedModels,
    modelSearchQuery,
    isCreatingNew,
    draftModels,
    isAddModelOpen,
    modelFormId,
    modelFormName,
    modelFormTags,
    modelFormType,
    editingModelOriginalId,
    deleteConfirm,
    testingConnection,
    connectionDiagnostics,
    testingModelId,
    modelTestResults,
    showMoreMenu,

    // setters
    setFormName,
    setFormBaseUrl,
    setFormApiFormat,
    setFormApiKey,
    setFormEnabled,
    setFormChatModel,
    setShowApiKey,
    setModelSearchQuery,
    setModelFormId,
    setModelFormName,
    setModelFormTags,
    setModelFormType,
    setEditingModelOriginalId,
    setIsAddModelOpen,
    setDeleteConfirm,
    setConnectionDiagnostics,
    setShowMoreMenu,

    // derived
    selectedProvider,
    allProviderModels,
    currentModelList,
    filteredFetchedModels,

    // actions
    refreshProviders,
    showToast,
    handleStartCreate,
    handleSwitchSettingsTab,
    handleCancelCreate,
    handleSelectProvider,
    requireHttpsUrl,
    handleFetchModels,
    handleSelectModel,
    handleAddFetchedModel,
    handleImportAllFetched,
    handleSaveCurrentProvider,
    handleSaveNewProvider,
    handleExecuteDelete,
    runConnectionTest,
    handleTestConnection,
    handleTestModel,
    resetModelForm,
    handleSaveModel,
  };
};

export type ProviderConfigCtrl = ReturnType<typeof useProviderConfig>;
