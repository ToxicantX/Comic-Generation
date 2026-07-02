import { app } from "/scripts/app.js";

const EXTENSION_NAME = "Comfy.ComicFlow.AutoRun";
const SWITCH_CLASS = "ComicFlowSwitch";
const DEFAULT_DELAY_MS = 500;

function boolValue(value) {
    return value === true || value === 1 || value === "true" || value === "True";
}

function widget(node, name) {
    return node.widgets?.find((item) => item.name === name);
}

function stageName(node) {
    return String(widget(node, "stage_name")?.value || node.title || SWITCH_CLASS);
}

function shouldConfirm(node) {
    const explicit = widget(node, "confirm_before_auto_run");
    if (explicit) {
        return boolValue(explicit.value);
    }
    return stageName(node).includes("生成");
}

function autoRunEnabled(node) {
    const auto = widget(node, "auto_run_on_open");
    return !auto || boolValue(auto.value);
}

function autoRunDelay(node) {
    const raw = Number(widget(node, "auto_run_delay_ms")?.value ?? DEFAULT_DELAY_MS);
    if (!Number.isFinite(raw)) {
        return DEFAULT_DELAY_MS;
    }
    return Math.max(0, Math.min(10000, raw));
}

async function queueCurrentWorkflow() {
    if (typeof app.queuePrompt === "function") {
        return app.queuePrompt(0);
    }
    const commandService = app.extensionManager?.commandService;
    if (commandService?.execute) {
        return commandService.execute("Comfy.QueuePrompt");
    }
    const button = document.querySelector(
        '[data-testid="queue-button"], button[aria-label*="Queue"], button[title*="Queue"]'
    );
    if (button) {
        button.click();
        return null;
    }
    throw new Error("Could not find a ComfyUI queue API or queue button.");
}

function scheduleAutoRun(node) {
    if (!autoRunEnabled(node)) {
        return;
    }
    const stage = stageName(node);
    if (shouldConfirm(node)) {
        const ok = window.confirm(`打开「${stage}」后立即运行当前工作流？`);
        if (!ok) {
            return;
        }
    }
    window.clearTimeout(node.__comicFlowAutoRunTimer);
    node.__comicFlowAutoRunTimer = window.setTimeout(async () => {
        try {
            console.info(`[${EXTENSION_NAME}] queue workflow from switch: ${stage}`);
            await queueCurrentWorkflow();
        } catch (error) {
            console.error(`[${EXTENSION_NAME}] auto-run failed`, error);
            window.alert(`自动运行失败：${error?.message || error}`);
        }
    }, autoRunDelay(node));
}

function patchEnabledWidget(node) {
    const enabled = widget(node, "enabled");
    if (!enabled || enabled.__comicFlowAutoRunPatched) {
        return;
    }
    enabled.__comicFlowAutoRunPatched = true;
    enabled.__comicFlowLastValue = boolValue(enabled.value);
    const original = enabled.callback;
    enabled.callback = function (value, ...args) {
        const previous = enabled.__comicFlowLastValue;
        const next = boolValue(value);
        enabled.__comicFlowLastValue = next;
        const result = original?.call(this, value, ...args);
        if (!previous && next) {
            scheduleAutoRun(node);
        }
        return result;
    };
}

app.registerExtension({
    name: EXTENSION_NAME,
    nodeCreated(node) {
        if (node.comfyClass === SWITCH_CLASS || node.constructor?.comfyClass === SWITCH_CLASS) {
            patchEnabledWidget(node);
        }
    },
    loadedGraphNode(node) {
        if (node.comfyClass === SWITCH_CLASS || node.constructor?.comfyClass === SWITCH_CLASS) {
            patchEnabledWidget(node);
        }
    },
});
