"use strict";
/* Bluehour control panel. Every control is generated from /api/schema, so it always matches the player. */

const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
        if (v === false || v == null) continue;
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat())
        if (kid != null)
            e.append(kid.nodeType ? kid : document.createTextNode(kid));
    return e;
}

/* ---------------------------------------------------------------- api */
const TOKEN = (() => {
    const url = new URL(location.href);
    const t = url.searchParams.get("t");
    try {
        if (t) {
            sessionStorage.setItem("bh_token", t);
            url.searchParams.delete("t");
            history.replaceState(null, "", url.pathname + url.hash);
        }
        return sessionStorage.getItem("bh_token") || t || "";
    } catch (e) {
        return t || "";
    }
})();

async function api(path, body) {
    const opt = { headers: { "X-Bluehour-Token": TOKEN } };
    if (body !== undefined) {
        opt.method = "POST";
        opt.headers["Content-Type"] = "application/json";
        opt.body = JSON.stringify(body);
    }
    let res;
    try {
        res = await fetch(path, opt);
    } catch (e) {
        throw new Error(
            "The control panel stopped responding. Is bluehour-gui still running?",
        );
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok)
        throw new Error(data.error || "Request failed (" + res.status + ")");
    return data;
}

let toastTimer;
function toast(msg, error) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast" + (error ? " error" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(
        () => {
            t.hidden = true;
        },
        error ? 6000 : 2600,
    );
}
const guard =
    (fn) =>
    async (...a) => {
        try {
            return await fn(...a);
        } catch (e) {
            toast(e.message, true);
        }
    };

/* ---------------------------------------------------------------- state */
const S = {
    schema: null,
    settings: {},
    playlist: [],
    presets: [],
    snap: null,
    running: false,
    restart: new Set(),
    logSeq: 0,
    logLines: [],
    controls: {},
    editing: null,
    monitors: [],
    cameras: [],
    doctor: null,
    doctorAsked: false,
    gamepad: null,
    tab: "play",
};
const FIELD = (name) => S.schema.fields.find((f) => f.name === name);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* ---------------------------------------------------------------- saving and live updates */
const pendingSave = {};
let saveTimer;
function queueSave(name, value) {
    pendingSave[name] = value;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(
        guard(async () => {
            const batch = Object.assign({}, pendingSave);
            for (const k of Object.keys(pendingSave)) delete pendingSave[k];
            await api("/api/settings", { settings: batch });
        }),
        250,
    );
}
const liveTimers = {};
function sendLive(name, value) {
    clearTimeout(liveTimers[name]);
    liveTimers[name] = setTimeout(
        guard(() => api("/api/command", { cmd: "set", name, value })),
        40,
    );
}
function setSetting(name, value) {
    const f = FIELD(name);
    S.settings[name] = value;
    queueSave(name, value);
    if (S.running) {
        if (f.live) sendLive(name, value);
        else {
            S.restart.add(f.label);
            renderBanner();
        }
    }
}
const act = guard((name) => api("/api/command", { cmd: "action", name }));

/* ---------------------------------------------------------------- field controls */
const num = (f, v) => (f.kind === "int" ? Math.round(v) : +(+v).toFixed(4));

function fieldBox(f, control, extra) {
    const live = f.live
        ? el(
              "span",
              { class: "live", title: "Changes while the player runs" },
              "live",
          )
        : null;
    const reset = el(
        "button",
        {
            class: "reset",
            type: "button",
            title: "Back to the default",
            onclick: () => control.reset(),
        },
        "default",
    );
    return el(
        "div",
        { class: "field", "data-field": f.name },
        el(
            "div",
            { class: "head" },
            el("span", { class: "lab", id: "lab-" + f.name }, f.label),
            live,
            reset,
        ),
        control.root,
        f.help ? el("div", { class: "help" }, f.help) : null,
        extra || null,
    );
}

function sliderControl(f, get, put, idx) {
    const lo = f.min,
        hi = f.max,
        step = f.step || 0.01;
    const range = el("input", {
        type: "range",
        min: lo,
        max: hi,
        step,
        "aria-labelledby": "lab-" + f.name,
    });
    const box = el("input", {
        type: "number",
        min: lo,
        max: hi,
        step,
        "aria-labelledby": "lab-" + f.name,
    });
    const apply = (v) => {
        range.value = v;
        box.value = v;
    };
    const commit = (raw) => {
        if (raw === "" || isNaN(+raw)) return;
        const v = Math.min(hi, Math.max(lo, num(f, raw)));
        apply(v);
        put(v);
    };
    range.addEventListener("input", () => {
        S.editing = f.name;
        commit(range.value);
    });
    range.addEventListener("change", () => {
        S.editing = null;
    });
    box.addEventListener("input", () => {
        S.editing = f.name;
    });
    box.addEventListener("change", () => {
        commit(box.value);
        S.editing = null;
    });
    return {
        range,
        box,
        set: apply,
        unit: f.unit ? el("span", { class: "unit" }, f.unit) : null,
    };
}

function buildField(f) {
    let control;
    if (f.kind === "float" || (f.kind === "int" && !f.auto)) {
        const s = sliderControl(f, null, (v) => setSetting(f.name, v));
        control = {
            root: el("div", { class: "ctl" }, s.range, s.box, s.unit),
            set: (v) => {
                if (S.editing !== f.name) s.set(v);
            },
            reset: () => {
                s.set(f.default);
                setSetting(f.name, f.default);
            },
        };
    } else if (f.kind === "vec4") {
        const rows = [],
            sliders = [];
        const cur = () => sliders.map((s) => +s.box.value);
        for (let i = 0; i < 4; i++) {
            const s = sliderControl(
                f,
                null,
                () => setSetting(f.name, cur()),
                i,
            );
            sliders.push(s);
            rows.push(
                el(
                    "div",
                    { class: "ctl" },
                    el("b", {}, "k" + i),
                    s.range,
                    s.box,
                ),
            );
        }
        control = {
            root: el("div", { class: "vec" }, rows),
            set: (v) => {
                if (S.editing !== f.name)
                    v.forEach((x, i) => sliders[i].set(x));
            },
            reset: () => {
                f.default.forEach((x, i) => sliders[i].set(x));
                setSetting(f.name, f.default.slice());
            },
        };
    } else if (f.kind === "choice") {
        const name = "seg-" + f.name;
        const inputs = f.choices.map((c) =>
            el("input", {
                type: "radio",
                name,
                value: c,
                onchange: () => setSetting(f.name, c),
            }),
        );
        const labels = f.choices.map((c, i) =>
            el(
                "label",
                {},
                inputs[i],
                el(
                    "span",
                    {},
                    c === "auto" ? "Auto" : c.toUpperCase() === c ? c : c,
                ),
            ),
        );
        control = {
            root: el(
                "div",
                {
                    class: "seg",
                    role: "radiogroup",
                    "aria-labelledby": "lab-" + f.name,
                },
                labels,
            ),
            set: (v) =>
                inputs.forEach((i) => {
                    i.checked = i.value === v;
                }),
            reset: () => {
                control.set(f.default);
                setSetting(f.name, f.default);
            },
        };
    } else if (f.kind === "bool") {
        const box = el("input", {
            type: "checkbox",
            id: "in-" + f.name,
            "aria-labelledby": "lab-" + f.name,
            onchange: () => setSetting(f.name, box.checked),
        });
        control = {
            root: el(
                "div",
                { class: "switch" },
                box,
                el(
                    "label",
                    { for: "in-" + f.name },
                    box.checked ? "On" : "Off",
                ),
            ),
            set: (v) => {
                box.checked = !!v;
                control.root.lastChild.textContent = v ? "On" : "Off";
            },
            reset: () => {
                control.set(f.default);
                setSetting(f.name, f.default);
            },
        };
        box.addEventListener("change", () => {
            control.root.lastChild.textContent = box.checked ? "On" : "Off";
        });
    } else if (f.kind === "int") {
        // optional integer such as the monitor or camera index: a list with Auto
        const select = el("select", {
            "aria-labelledby": "lab-" + f.name,
            onchange: () =>
                setSetting(f.name, select.value === "" ? null : +select.value),
        });
        const fill = (v) => {
            const items =
                f.name === "monitor"
                    ? S.monitors
                    : f.name === "camera"
                      ? S.cameras
                      : [];
            const known = new Set(items.map((i) => i.index));
            const base = [];
            for (
                let i = 0;
                i <= Math.min(f.max, f.name === "monitor" ? 5 : 3);
                i++
            )
                if (!known.has(i)) base.push({ index: i });
            const all = items.concat(base).sort((a, b) => a.index - b.index);
            select.replaceChildren(
                el("option", { value: "" }, "Auto"),
                all.map((i) =>
                    el("option", { value: i.index }, optionLabel(f.name, i)),
                ),
            );
            select.value = v == null ? "" : String(v);
            if (select.value !== (v == null ? "" : String(v))) {
                select.append(el("option", { value: v }, "#" + v));
                select.value = String(v);
            }
        };
        const detect = el(
            "button",
            {
                class: "btn small",
                type: "button",
                onclick: guard(() => detect_(f.name)),
            },
            "Detect",
        );
        control = {
            root: el("div", { class: "ctl" }, select, detect),
            set: (v) => {
                if (document.activeElement !== select) fill(v);
            },
            reset: () => {
                fill(null);
                setSetting(f.name, null);
            },
            refill: () => fill(S.settings[f.name]),
        };
    } else {
        // text
        const list = f.suggestions.length
            ? el(
                  "datalist",
                  { id: "dl-" + f.name },
                  f.suggestions.map((s) => el("option", { value: s })),
              )
            : null;
        const input = el("input", {
            type: "text",
            spellcheck: "false",
            autocomplete: "off",
            list: list ? list.id : false,
            placeholder: f.default || (f.auto ? "default" : ""),
            "aria-labelledby": "lab-" + f.name,
        });
        const err = el("div", { class: "err", hidden: true });
        input.addEventListener(
            "change",
            guard(async () => {
                try {
                    await api("/api/settings", {
                        settings: { [f.name]: input.value },
                    });
                    err.hidden = true;
                    setSetting(f.name, input.value.trim());
                } catch (e) {
                    err.textContent = e.message;
                    err.hidden = false;
                }
            }),
        );
        control = {
            root: el("div", {}, el("div", { class: "ctl" }, input, list), err),
            set: (v) => {
                if (document.activeElement !== input) input.value = v || "";
            },
            reset: () => {
                input.value = f.default;
                err.hidden = true;
                setSetting(f.name, f.default);
            },
        };
    }
    S.controls[f.name] = control;
    return fieldBox(f, control);
}

function optionLabel(kind, i) {
    if (kind === "monitor") {
        return i.name
            ? i.index +
                  ": " +
                  i.name +
                  " (" +
                  i.width +
                  "x" +
                  i.height +
                  " @ " +
                  i.hz +
                  " Hz)" +
                  (i.primary ? ", primary" : "")
            : "Monitor " + i.index;
    }
    return i.width
        ? "Camera " +
              i.index +
              " (" +
              i.width +
              "x" +
              i.height +
              (i.dk2 ? ", DK2 camera" : "") +
              ")"
        : "Camera " + i.index;
}

async function detect_(name) {
    const what = name === "monitor" ? "monitors" : "cameras";
    toast("Looking for " + what + "...");
    const data = await api("/api/detect/" + what);
    S[what] = data[what];
    S.controls[name].refill();
    toast(
        data[what].length
            ? "Found " + data[what].length
            : "None found. See the Output tab.",
        !data[what].length,
    );
    if (!data[what].length)
        addLog(data.output.map((t) => ({ src: "tool", text: t })));
}

function fieldsCard(title, names, intro, extra) {
    return el(
        "section",
        { class: "card" },
        el("h3", {}, title),
        intro ? el("p", { class: "muted" }, intro) : null,
        el(
            "div",
            { class: "fields" },
            names.map((n) => buildField(FIELD(n))),
        ),
        extra || null,
    );
}

function toolButton(id) {
    const t = S.schema.tools.find((x) => x.id === id);
    const b = el(
        "button",
        {
            class: "btn small",
            type: "button",
            "data-tool": id,
            title: t.help,
            onclick: guard(() => runTool(id)),
        },
        t.label,
    );
    return b;
}
async function runTool(id) {
    await api("/api/tool", { tool: id });
    if (id !== "doctor") showTab("output");
}

/* ---------------------------------------------------------------- panels */
const KEYS = [
    ["Pause or play", "Space", "A", "A"],
    ["Recenter view", "R", "B", "B"],
    [
        "Seek 10 s back / forward",
        "Left / Right",
        "D-pad left / right",
        "D-pad left / right",
    ],
    ["Volume down / up", "Down / Up", "D-pad down / up", "D-pad down / up"],
    ["Seek 60 s back / forward", "PgDn / PgUp", "Minus / Plus", "LB / RB"],
    ["Cycle mono / SBS / OU", "S", "1", "X"],
    ["Cycle flat / curved / VR180 / VR360", "1 2 3 4 pick one", "2", "Y"],
    ["Cycle position source", "V", "Home", "Start"],
    ["Mute", "M", "", "Back"],
    ["Next / previous file", "N / P", "", ""],
    ["Subtitles / audio track", "T / A", "", ""],
    ["Swap eyes", "X", "", ""],
    ["Rotate output", "F", "", ""],
    ["Screen size", "- / =", "", ""],
    ["Screen distance", "9 / 0", "", ""],
    ["IPD", "[ / ]", "", ""],
    ["Field of view", "; / '", "", ""],
    ["Lens distortion k1", ", / .", "", ""],
    ["Quit the player", "Esc or Q", "", ""],
];

const PANELS = {
    play() {
        const wrap = el("div", { class: "panel" });
        wrap.append(el("section", { class: "card", id: "setup-card" }));
        const list = el(
            "section",
            { class: "card" },
            el("h3", {}, "Playlist"),
            el("div", { id: "playlist" }),
            el(
                "div",
                { class: "row", style: "margin-top:10px" },
                el(
                    "button",
                    {
                        class: "btn small primary",
                        type: "button",
                        onclick: guard(openPicker),
                    },
                    "Add videos",
                ),
                el("input", {
                    type: "text",
                    id: "url-in",
                    placeholder: "or paste a web address",
                    style: "flex:1;min-width:200px",
                    spellcheck: "false",
                    "aria-label": "Web address",
                    onkeydown: (e) => {
                        if (e.key === "Enter") addUrl();
                    },
                }),
                el(
                    "button",
                    { class: "btn small", type: "button", onclick: addUrl },
                    "Add address",
                ),
                el(
                    "button",
                    { class: "btn small", type: "button", onclick: clearList },
                    "Clear",
                ),
            ),
            el(
                "p",
                { class: "help", style: "margin-top:8px" },
                "The layout (flat, VR180, 3D) is read from each file name unless you set it on the Image tab. Names like movie_180_sbs.mp4 work.",
            ),
        );
        const presets = el(
            "section",
            { class: "card" },
            el("h3", {}, "Presets"),
            el(
                "p",
                { class: "muted" },
                "Save every setting under a name, for example one per headset position or one per movie type.",
            ),
            el(
                "div",
                { class: "row" },
                el("select", { id: "preset-sel", "aria-label": "Preset" }),
                el(
                    "button",
                    { class: "btn small", type: "button", onclick: presetLoad },
                    "Load",
                ),
                el(
                    "button",
                    {
                        class: "btn small",
                        type: "button",
                        onclick: presetDelete,
                    },
                    "Delete",
                ),
                el("input", {
                    type: "text",
                    id: "preset-name",
                    placeholder: "New preset name",
                    maxlength: "60",
                    "aria-label": "Preset name",
                    style: "min-width:160px",
                }),
                el(
                    "button",
                    { class: "btn small", type: "button", onclick: presetSave },
                    "Save current",
                ),
            ),
        );
        wrap.append(list, presets);
        return wrap;
    },
    image() {
        const wrap = el("div", { class: "panel" });
        wrap.append(el("div", { class: "card", id: "headset-values" }));
        wrap.append(
            fieldsCard(
                "Layout",
                ["proj", "stereo", "swap_eyes"],
                "How the video is laid out in the frame.",
            ),
            fieldsCard(
                "Screen",
                ["screen_width", "distance", "ipd", "fov_scale"],
                "Flat and curved screens use size and distance.",
            ),
            fieldsCard(
                "Lens",
                ["k", "ca"],
                "Lens distortion and colour fringing for the DK2 optics. Adjust k1 first.",
            ),
        );
        return wrap;
    },
    display() {
        return el(
            "div",
            { class: "panel" },
            fieldsCard(
                "Display",
                ["monitor", "windowed", "rotate"],
                "Make the DK2 an extended monitor at 1920x1080, 75 Hz. If the picture is on its side, change Rotate output until it is upright.",
            ),
        );
    },
    tracking() {
        return el(
            "div",
            { class: "panel" },
            fieldsCard(
                "Head rotation",
                ["tracking", "axis_map", "no_led_enable"],
                "Rotation comes from the DK2 motion sensor over USB, with mouse look as the fallback.",
            ),
            fieldsCard(
                "Leaning and moving",
                ["position", "move_scale"],
                "Used on flat and curved screens. VR180 and VR360 video has no depth.",
            ),
            fieldsCard(
                "DK2 camera",
                [
                    "camera",
                    "cam_fov",
                    "cam_distance",
                    "cam_threshold",
                    "cam_axis_map",
                ],
                "Needs a USB 3.0 port and the sync cable. Run the camera test and lean 10 cm to check the numbers.",
                el(
                    "div",
                    { class: "row", style: "margin-top:12px" },
                    toolButton("list_cameras"),
                    toolButton("cam_test"),
                ),
            ),
        );
    },
    controllers() {
        const wrap = el("div", { class: "panel" });
        wrap.append(
            fieldsCard(
                "Wii Remote",
                [
                    "wii",
                    "wii_swap",
                    "wii_ir_level",
                    "wii_fov",
                    "wii_distance",
                    "wii_axis_map",
                ],
                "One remote is a controller. A second can watch the headset LEDs as a position camera. Needs a Bluetooth adapter.",
                el(
                    "div",
                    { class: "row", style: "margin-top:12px" },
                    toolButton("wii_test"),
                ),
            ),
        );
        wrap.append(
            fieldsCard(
                "USB gamepads",
                ["no_gamepad", "pad_file"],
                "Xbox One, PS3 and most USB pads work as remotes. The raphnet adapter needs to be taught once.",
                el(
                    "div",
                    { class: "row", style: "margin-top:12px" },
                    toolButton("pad_test"),
                    toolButton("pad_config"),
                ),
            ),
        );
        wrap.append(
            el(
                "section",
                { class: "card" },
                el("h3", {}, "Controller mappings"),
                el("div", { id: "mappings" }),
            ),
        );
        return wrap;
    },
    playback() {
        return el(
            "div",
            { class: "panel" },
            fieldsCard(
                "Playback",
                ["volume", "hwdec", "audio_device", "debug"],
                "",
            ),
        );
    },
    tools() {
        const tools = S.schema.tools;
        const wrap = el("div", { class: "panel" });
        wrap.append(
            el(
                "section",
                { class: "card" },
                el("h3", {}, "Setup check"),
                el(
                    "p",
                    { class: "muted" },
                    "Looks for the Python packages, libmpv, the DK2, Wii Remotes and controllers.",
                ),
                el("div", { class: "row" }, toolButton("doctor")),
                el("ul", {
                    class: "list checks",
                    id: "doctor-list",
                    style: "margin-top:10px",
                }),
            ),
        );
        wrap.append(
            el(
                "section",
                { class: "card" },
                el("h3", {}, "Helpers"),
                el(
                    "p",
                    { class: "muted" },
                    "These open their own window or print to the Output tab. Stop the one that is running before starting another.",
                ),
                el(
                    "ul",
                    { class: "list" },
                    tools
                        .filter((t) => t.id !== "doctor")
                        .map((t) =>
                            el(
                                "li",
                                {},
                                toolButton(t.id),
                                el(
                                    "span",
                                    {
                                        class: "name muted",
                                        style: "white-space:normal",
                                    },
                                    t.help,
                                ),
                            ),
                        ),
                ),
                el(
                    "div",
                    { class: "row", style: "margin-top:10px" },
                    el(
                        "button",
                        {
                            class: "btn small",
                            id: "tool-stop",
                            type: "button",
                            hidden: true,
                            onclick: guard(() =>
                                api("/api/tool", { action: "stop" }),
                            ),
                        },
                        "Stop helper",
                    ),
                ),
            ),
        );
        return wrap;
    },
    output() {
        return el(
            "div",
            { class: "panel" },
            el(
                "div",
                { class: "row", style: "margin-bottom:8px" },
                el("h2", { style: "margin:0;flex:1" }, "Output"),
                el(
                    "button",
                    {
                        class: "btn small",
                        type: "button",
                        onclick: () => {
                            S.logLines = [];
                            renderLog(true);
                        },
                    },
                    "Clear",
                ),
            ),
            el("pre", {
                class: "log",
                id: "log",
                tabindex: "0",
                "aria-label": "Player and helper output",
            }),
        );
    },
    help() {
        const row = (r) =>
            el(
                "tr",
                {},
                r.map((c) => el("td", {}, c)),
            );
        return el(
            "div",
            { class: "panel" },
            el(
                "section",
                { class: "card" },
                el("h3", {}, "Controls"),
                el(
                    "p",
                    { class: "muted" },
                    "The same actions work from the keyboard (with the headset window focused), a Wii Remote, a gamepad, and the remote bar below.",
                ),
                el(
                    "div",
                    { class: "tablewrap" },
                    el(
                        "table",
                        {},
                        el(
                            "thead",
                            {},
                            el(
                                "tr",
                                {},
                                [
                                    "Action",
                                    "Keyboard",
                                    "Wii Remote",
                                    "Gamepad",
                                ].map((h) => el("th", {}, h)),
                            ),
                        ),
                        el("tbody", {}, KEYS.map(row)),
                    ),
                ),
            ),
            el(
                "section",
                { class: "card" },
                el("h3", {}, "More help"),
                el(
                    "ul",
                    {},
                    el(
                        "li",
                        {},
                        el(
                            "a",
                            {
                                href: "https://mosberg.github.io/bluehour-vr/",
                                target: "_blank",
                                rel: "noopener",
                            },
                            "Guides and troubleshooting",
                        ),
                    ),
                    el(
                        "li",
                        {},
                        el(
                            "a",
                            {
                                href: "https://github.com/Mosberg/bluehour-vr/issues/new/choose",
                                target: "_blank",
                                rel: "noopener",
                            },
                            "Report a problem or share hardware results",
                        ),
                    ),
                    el(
                        "li",
                        {},
                        "Bluehour ",
                        el("span", { id: "version" }, S.schema.version),
                    ),
                ),
                el(
                    "p",
                    { class: "muted" },
                    "This panel only listens on your own computer. It is not reachable from other devices.",
                ),
            ),
        );
    },
};
const TABS = [
    ["play", "Play"],
    ["image", "Image"],
    ["display", "Display"],
    ["tracking", "Tracking"],
    ["controllers", "Controllers"],
    ["playback", "Playback"],
    ["tools", "Tools"],
    ["output", "Output"],
    ["help", "Help"],
];

function buildPanels() {
    const tabs = $("#tabs"),
        host = $("#panels");
    tabs.replaceChildren();
    host.replaceChildren();
    for (const [id, label] of TABS) {
        tabs.append(
            el(
                "button",
                {
                    role: "tab",
                    id: "tab-" + id,
                    "aria-controls": "p-" + id,
                    "aria-selected": "false",
                    type: "button",
                    onclick: () => showTab(id),
                    onkeydown: tabKeys,
                },
                label,
            ),
        );
        host.append(
            el(
                "div",
                {
                    id: "p-" + id,
                    role: "tabpanel",
                    "aria-labelledby": "tab-" + id,
                    hidden: true,
                },
                PANELS[id](),
            ),
        );
    }
    for (const f of S.schema.fields)
        if (!S.controls[f.name])
            console.warn("Setting without a control:", f.name);
    applySettingsToControls();
}
function tabKeys(e) {
    const ids = TABS.map((t) => t[0]);
    let i = ids.indexOf(S.tab);
    if (e.key === "ArrowDown" || e.key === "ArrowRight")
        i = (i + 1) % ids.length;
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft")
        i = (i + ids.length - 1) % ids.length;
    else return;
    e.preventDefault();
    showTab(ids[i]);
    $("#tab-" + ids[i]).focus();
}
function showTab(id) {
    S.tab = id;
    for (const [t] of TABS) {
        $("#p-" + t).hidden = t !== id;
        $("#tab-" + t).setAttribute(
            "aria-selected",
            t === id ? "true" : "false",
        );
        $("#tab-" + t).tabIndex = t === id ? 0 : -1;
    }
    if (id === "output") renderLog(true);
    if (id === "controllers") loadMappings();
    try {
        sessionStorage.setItem("bh_tab", id);
    } catch (e) {
        /* private mode */
    }
}
function applySettingsToControls() {
    for (const f of S.schema.fields)
        if (S.controls[f.name]) S.controls[f.name].set(S.settings[f.name]);
}

/* ---------------------------------------------------------------- playlist, presets */
function renderPlaylist() {
    const host = $("#playlist");
    if (!host) return;
    const ps = S.snap && S.snap.player_state;
    const playing =
        ps && ps.playlist && ps.playlist.length === S.playlist.length
            ? ps.index
            : -1;
    if (!S.playlist.length) {
        host.replaceChildren(
            el(
                "div",
                { class: "empty" },
                "No videos yet. Add some, then press Start player.",
            ),
        );
        return;
    }
    host.replaceChildren(
        el(
            "ul",
            { class: "list" },
            S.playlist.map((p, i) =>
                el(
                    "li",
                    { class: i === playing ? "now" : "" },
                    el(
                        "span",
                        { class: "name", title: p },
                        (i === playing ? "Playing: " : "") +
                            p.split(/[\\/]/).pop(),
                    ),
                    S.running
                        ? el(
                              "button",
                              {
                                  class: "btn small",
                                  type: "button",
                                  title: "Play this now",
                                  onclick: guard(() =>
                                      api("/api/command", {
                                          cmd: "play_index",
                                          index: i,
                                      }),
                                  ),
                              },
                              "Play",
                          )
                        : null,
                    el(
                        "button",
                        {
                            class: "icon",
                            type: "button",
                            "aria-label": "Move up",
                            disabled: i === 0,
                            onclick: () => moveItem(i, -1),
                        },
                        "↑",
                    ),
                    el(
                        "button",
                        {
                            class: "icon",
                            type: "button",
                            "aria-label": "Move down",
                            disabled: i === S.playlist.length - 1,
                            onclick: () => moveItem(i, 1),
                        },
                        "↓",
                    ),
                    el(
                        "button",
                        {
                            class: "icon",
                            type: "button",
                            "aria-label": "Remove",
                            onclick: () => {
                                S.playlist.splice(i, 1);
                                savePlaylist();
                            },
                        },
                        "×",
                    ),
                ),
            ),
        ),
    );
}
const savePlaylist = guard(async () => {
    await api("/api/playlist", { playlist: S.playlist });
    renderPlaylist();
});
function moveItem(i, d) {
    const j = i + d;
    [S.playlist[i], S.playlist[j]] = [S.playlist[j], S.playlist[i]];
    savePlaylist();
}
function clearList() {
    S.playlist = [];
    savePlaylist();
}
const addFiles = guard(async (files) => {
    S.playlist.push(...files);
    await savePlaylist();
    if (S.running)
        await api("/api/command", { cmd: "load", files, mode: "append" });
});
function addUrl() {
    const input = $("#url-in"),
        v = input.value.trim();
    if (!v) return;
    if (!/^(https?|rtsp|rtmp|mms):\/\/\S+$/i.test(v)) {
        toast("That does not look like a web address.", true);
        return;
    }
    input.value = "";
    addFiles([v]);
}
function renderPresets() {
    const sel = $("#preset-sel");
    if (!sel) return;
    const cur = sel.value;
    sel.replaceChildren(
        ...(S.presets.length
            ? S.presets.map((p) => el("option", { value: p }, p))
            : [el("option", { value: "" }, "No presets yet")]),
    );
    if (S.presets.includes(cur)) sel.value = cur;
}
const presetSave = guard(async () => {
    const name = $("#preset-name").value.trim() || $("#preset-sel").value;
    const data = await api("/api/presets", { action: "save", name });
    S.presets = data.presets;
    renderPresets();
    $("#preset-sel").value = name;
    $("#preset-name").value = "";
    toast("Saved preset " + name);
});
const presetLoad = guard(async () => {
    const name = $("#preset-sel").value;
    if (!name) return;
    const data = await api("/api/presets", { action: "load", name });
    S.settings = data.settings;
    applySettingsToControls();
    if (S.running) {
        S.restart.add("Preset " + name);
        pushLiveSettings();
        renderBanner();
    }
    toast("Loaded preset " + name);
});
const presetDelete = guard(async () => {
    const name = $("#preset-sel").value;
    if (!name) return;
    const data = await api("/api/presets", { action: "delete", name });
    S.presets = data.presets;
    renderPresets();
});
function pushLiveSettings() {
    for (const f of S.schema.fields)
        if (f.live && S.settings[f.name] !== undefined)
            sendLive(f.name, S.settings[f.name]);
}

/* ---------------------------------------------------------------- file picker */
let pickDir = "";
const pk = { list: () => $("#pk-list"), sel: new Set() };
const openPicker = guard(async () => {
    pk.sel.clear();
    await loadDir(pickDir);
    $("#picker").showModal();
    $("#pk-path").focus();
});
async function loadDir(path) {
    const d = await api("/api/fs?path=" + encodeURIComponent(path || ""));
    pickDir = d.path;
    $("#pk-path").value = d.path;
    $("#pk-up").disabled = !d.parent;
    $("#pk-up").dataset.to = d.parent || "";
    $("#pk-home").dataset.to = d.home;
    const roots = $("#pk-roots");
    roots.replaceChildren(...d.roots.map((r) => el("option", { value: r }, r)));
    roots.value = d.roots.find((r) => d.path.startsWith(r)) || d.roots[0];
    const showAll = $("#pk-all").checked;
    const sep = d.sep;
    const rows = d.entries
        .filter((e) => e.dir || e.media || showAll)
        .map((e) => {
            const full = d.path.replace(/[\\/]$/, "") + sep + e.name;
            const box = e.dir
                ? null
                : el("input", {
                      type: "checkbox",
                      "aria-label": "Select " + e.name,
                      checked: pk.sel.has(full),
                      onclick: (ev) => {
                          ev.stopPropagation();
                          box.checked ? pk.sel.add(full) : pk.sel.delete(full);
                      },
                  });
            return el(
                "li",
                {
                    class: e.media ? "media" : "",
                    onclick: guard(() => {
                        if (e.dir) return loadDir(full);
                        box.checked = !box.checked;
                        box.checked ? pk.sel.add(full) : pk.sel.delete(full);
                    }),
                },
                box,
                el("span", {}, e.dir ? "📁" : "🎬"),
                el("span", { class: "name" }, e.name),
                e.size != null
                    ? el("span", { class: "size" }, humanSize(e.size))
                    : null,
            );
        });
    pk.list().replaceChildren(...rows);
    $("#pk-msg").textContent = rows.length
        ? ""
        : "No folders or videos here. Tick Show all files to see everything.";
}
const humanSize = (n) =>
    n > 1e9
        ? (n / 1e9).toFixed(1) + " GB"
        : n > 1e6
          ? (n / 1e6).toFixed(0) + " MB"
          : Math.max(1, Math.round(n / 1e3)) + " kB";
function initPicker() {
    $("#pk-up").onclick = guard(() => loadDir($("#pk-up").dataset.to));
    $("#pk-home").onclick = guard(() => loadDir($("#pk-home").dataset.to));
    $("#pk-roots").onchange = guard(() => loadDir($("#pk-roots").value));
    $("#pk-all").onchange = guard(() => loadDir(pickDir));
    $("#pk-path").onkeydown = guard((e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            return loadDir(e.target.value);
        }
    });
    $("#pk-add").onclick = () => {
        const files = [...pk.sel];
        $("#picker").close();
        if (files.length) addFiles(files);
    };
}

/* ---------------------------------------------------------------- gamepad mappings */
const SPEC_HELP =
    "button:3 (a button), hat:0:1/2/4/8 (D-pad up/right/down/left), axis:1:- or axis:1:+ (stick or trigger direction)";
const loadMappings = guard(async () => {
    S.gamepad = await api("/api/gamepad");
    renderMappings();
});
function renderMappings() {
    const host = $("#mappings"),
        g = S.gamepad;
    if (!host || !g) return;
    const names = Object.keys(g.config);
    const defTable = el(
        "details",
        {},
        el("summary", {}, "Default mapping for Xbox-style pads"),
        el(
            "div",
            { class: "tablewrap" },
            el(
                "table",
                {},
                el(
                    "tbody",
                    {},
                    g.actions.map((a) =>
                        el(
                            "tr",
                            {},
                            el("td", {}, a.label),
                            el(
                                "td",
                                {},
                                el("code", {}, g.defaults[a.id] || ""),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    );
    const cards = names.map((name) => {
        const inputs = {};
        const table = el(
            "table",
            { class: "map" },
            el(
                "tbody",
                {},
                g.actions.map((a) => {
                    const input = el("input", {
                        type: "text",
                        spellcheck: "false",
                        value: g.config[name][a.id] || "",
                        placeholder: "not set",
                        "aria-label": a.label + " for " + name,
                    });
                    inputs[a.id] = input;
                    return el(
                        "tr",
                        {},
                        el("td", {}, a.label),
                        el("td", {}, input),
                    );
                }),
            ),
        );
        return el(
            "div",
            { style: "margin-top:14px" },
            el("h3", {}, name),
            table,
            el(
                "div",
                { class: "row", style: "margin-top:8px" },
                el(
                    "button",
                    {
                        class: "btn small primary",
                        type: "button",
                        onclick: guard(async () => {
                            const m = {};
                            for (const [id, input] of Object.entries(inputs))
                                if (input.value.trim())
                                    m[id] = input.value.trim();
                            g.config[name] = m;
                            await api("/api/gamepad", { config: g.config });
                            toast("Saved mapping for " + name);
                        }),
                    },
                    "Save",
                ),
                el(
                    "button",
                    {
                        class: "btn small",
                        type: "button",
                        onclick: guard(async () => {
                            delete g.config[name];
                            await api("/api/gamepad", { config: g.config });
                            renderMappings();
                        }),
                    },
                    "Delete",
                ),
            ),
        );
    });
    const addName = el("input", {
        type: "text",
        placeholder: "Controller name exactly as shown in the test",
        style: "flex:1;min-width:220px",
        "aria-label": "Controller name",
    });
    host.replaceChildren(
        el(
            "p",
            { class: "muted" },
            "Learned mappings are stored here per controller name. Teach a controller with the button above, then fine-tune it here. Controls are written as " +
                SPEC_HELP +
                ".",
        ),
        defTable,
        ...cards,
        el(
            "div",
            { class: "row", style: "margin-top:14px" },
            addName,
            el(
                "button",
                {
                    class: "btn small",
                    type: "button",
                    onclick: guard(async () => {
                        const n = addName.value.trim();
                        if (!n || g.config[n]) return;
                        g.config[n] = Object.assign({}, g.defaults);
                        await api("/api/gamepad", { config: g.config });
                        renderMappings();
                    }),
                },
                "Add controller",
            ),
        ),
        el("p", { class: "help" }, "File: " + g.file),
    );
}

/* ---------------------------------------------------------------- remote bar, status, log */
const fmt = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600),
        m = Math.floor((s % 3600) / 60),
        x = s % 60;
    return (
        (h ? h + ":" + String(m).padStart(2, "0") : m) +
        ":" +
        String(x).padStart(2, "0")
    );
};
let seeking = false,
    volDrag = false;
function initRemote() {
    document
        .querySelectorAll("#remote [data-act]")
        .forEach((b) => b.addEventListener("click", () => act(b.dataset.act)));
    const seek = $("#r-seek"),
        vol = $("#r-vol");
    seek.addEventListener("input", () => {
        seeking = true;
        $("#r-time").textContent = fmt(+seek.value);
    });
    seek.addEventListener(
        "change",
        guard(async () => {
            await api("/api/command", {
                cmd: "seek",
                value: +seek.value,
                mode: "absolute",
            });
            seeking = false;
        }),
    );
    vol.addEventListener("input", () => {
        volDrag = true;
        sendLive("volume", +vol.value);
    });
    vol.addEventListener("change", () => {
        volDrag = false;
        setSetting("volume", +vol.value);
        S.controls.volume.set(+vol.value);
    });
}
const LIVE_SYNC = [
    "swap_eyes",
    "rotate",
    "screen_width",
    "distance",
    "ipd",
    "fov_scale",
    "k",
    "ca",
    "position",
    "move_scale",
    "volume",
];
function renderState() {
    const snap = S.snap,
        ps = snap.player_state;
    S.running = snap.player_running;
    const status = $("#status");
    status.className = "status" + (S.running ? " running" : "");
    let text = "Player stopped";
    if (S.running)
        text = ps
            ? (ps.pause ? "Paused" : "Playing") +
              (ps.file ? ": " + ps.file : "")
            : "Starting...";
    else if (snap.last_exit.player > 0) {
        text = "Player stopped with an error. See Output.";
        status.className = "status error";
    }
    $("#status-text").textContent = text;
    $("#btn-start").hidden = false;
    $("#btn-start").textContent = S.running ? "Restart player" : "Start player";
    $("#btn-stop").hidden = !S.running;
    $("#remote").hidden = !S.running;
    if (!S.running && S.restart.size) {
        S.restart.clear();
    }
    renderBanner();
    const stopTool = $("#tool-stop");
    if (stopTool) stopTool.hidden = !snap.tool_running;
    document.querySelectorAll("[data-tool]").forEach((b) => {
        b.disabled = snap.tool_running && b.dataset.tool !== snap.tool;
        if (b.dataset.tool === snap.tool) b.disabled = true;
    });
    if (ps) {
        $("#r-pause").innerHTML = ps.pause ? "&#9658;" : "&#10074;&#10074;";
        $("#r-mute").innerHTML = ps.mute ? "&#128263;" : "&#128266;";
        if (!seeking) {
            $("#r-seek").max = Math.max(1, ps.duration || 1);
            $("#r-seek").value = ps.time;
            $("#r-time").textContent = fmt(ps.time);
        }
        $("#r-dur").textContent = fmt(ps.duration);
        if (!volDrag && document.activeElement !== $("#r-vol"))
            $("#r-vol").value = ps.volume;
        const bits = [
            ps.proj +
                (ps.stereo !== "mono" ? " " + ps.stereo.toUpperCase() : ""),
            "head: " + ps.head_tracker,
            "position: " +
                ps.position +
                (ps.position === "auto" ? " (" + ps.position_now + ")" : ""),
        ];
        if (ps.wii_controller) bits.push("Wii Remote");
        if (ps.gamepads)
            bits.push(ps.gamepads + " gamepad" + (ps.gamepads > 1 ? "s" : ""));
        $("#r-now").textContent = bits.join("  |  ");
        for (const name of LIVE_SYNC)
            if (S.editing !== name && S.controls[name])
                S.controls[name].set(ps[name]);
        renderHeadsetValues(ps);
    }
    renderPlaylist();
}
function renderHeadsetValues(ps) {
    const host = $("#headset-values");
    if (!host) return;
    host.hidden = !S.running;
    if (!S.running || !ps) return;
    if (!host.firstChild) {
        host.append(
            el("p", { id: "hv-text", class: "muted" }),
            el(
                "button",
                {
                    class: "btn small",
                    type: "button",
                    onclick: guard(saveHeadset),
                },
                "Keep these values as my settings",
            ),
        );
    }
    $("#hv-text").textContent =
        "In the headset now: " +
        ps.proj +
        ", " +
        ps.stereo +
        (ps.swap_eyes ? ", eyes swapped" : "") +
        ". Sliders below follow changes made with the keyboard, Wii Remote or gamepad.";
}
async function saveHeadset() {
    const ps = S.snap.player_state;
    if (!ps) return;
    const batch = {};
    for (const n of LIVE_SYNC) batch[n] = ps[n];
    if (S.settings.proj !== "auto") batch.proj = ps.proj;
    if (S.settings.stereo !== "auto") batch.stereo = ps.stereo;
    const r = await api("/api/settings", { settings: batch });
    S.settings = r.settings;
    toast("Saved the current headset values.");
}
function renderBanner() {
    const b = $("#restart-banner");
    const items = [...S.restart];
    b.hidden = !(S.running && items.length);
    if (!b.hidden)
        $("#restart-text").textContent =
            "Restart the player to apply: " + items.join(", ") + ".";
}
function addLog(lines) {
    for (const l of lines) S.logLines.push(l);
    if (S.logLines.length > 1500)
        S.logLines.splice(0, S.logLines.length - 1500);
    renderLog(false);
}
function renderLog(full) {
    const pre = $("#log");
    if (!pre || (S.tab !== "output" && !full)) return;
    const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
    pre.replaceChildren(
        ...S.logLines.map((l) => el("div", { class: l.src }, l.text)),
    );
    if (stick || full) pre.scrollTop = pre.scrollHeight;
}
function renderDoctor() {
    const list = $("#doctor-list"),
        card = $("#setup-card");
    const d = S.doctor;
    if (list)
        list.replaceChildren(
            ...(d
                ? d.map((c) =>
                      el(
                          "li",
                          {},
                          el(
                              "span",
                              { class: "pill " + c.status },
                              c.status === "ok"
                                  ? "OK"
                                  : c.status === "warn"
                                    ? "Optional"
                                    : "Fix",
                          ),
                          el(
                              "div",
                              {},
                              el("strong", {}, c.name),
                              el("div", { class: "muted" }, c.detail),
                              c.hint && c.status !== "ok"
                                  ? el("div", { class: "help" }, c.hint)
                                  : null,
                          ),
                      ),
                  )
                : []),
        );
    if (!card) return;
    if (!d) {
        card.replaceChildren(
            el("h3", {}, "Setup"),
            el("p", { class: "muted" }, "Checking your setup..."),
        );
        return;
    }
    const fails = d.filter((c) => c.status === "fail"),
        warns = d.filter((c) => c.status === "warn");
    card.replaceChildren(
        el(
            "h3",
            {},
            fails.length ? "Setup needs attention" : "Setup looks good",
        ),
        fails.length
            ? el(
                  "ul",
                  {},
                  fails.map((c) =>
                      el(
                          "li",
                          {},
                          el("strong", {}, c.name + ": "),
                          c.hint || c.detail,
                      ),
                  ),
              )
            : el(
                  "p",
                  { class: "muted" },
                  warns.length
                      ? warns.length +
                            " optional item" +
                            (warns.length > 1 ? "s" : "") +
                            " not found (for example the headset or a Wii Remote). Details are on the Tools tab."
                      : "Everything the player needs was found.",
              ),
        el(
            "div",
            { class: "row" },
            el(
                "button",
                {
                    class: "btn small",
                    type: "button",
                    onclick: guard(() => runTool("doctor")),
                },
                "Check again",
            ),
        ),
    );
}

/* ---------------------------------------------------------------- start, stop, polling + WebSocket */
const startPlayer = guard(async () => {
    if (!S.playlist.length) {
        toast("Add a video to the playlist first.", true);
        showTab("play");
        return;
    }
    if (S.running) {
        await api("/api/stop", {});
        await waitFor(() => !S.running);
    }
    S.restart.clear();
    await api("/api/play", {});
    toast("Starting the player...");
});
const stopPlayer = guard(() => api("/api/stop", {}));
const quit = guard(async () => {
    if (!confirm("Stop the player and close the control panel?")) return;
    await api("/api/shutdown", {});
    document.body.replaceChildren(
        el(
            "main",
            { style: "padding:40px" },
            el("h2", {}, "Bluehour control panel closed"),
            el("p", {}, "You can close this window."),
        ),
    );
});
const waitFor = (cond, ms = 6000) =>
    new Promise((res) => {
        const t0 = Date.now();
        const id = setInterval(() => {
            if (cond() || Date.now() - t0 > ms) {
                clearInterval(id);
                res();
            }
        }, 100);
    });

/* ---- WebSocket for live state updates ---- */
let ws;
function wsUrl() {
    const u = new URL(location.href);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws";
    u.searchParams.set("t", TOKEN);
    return u.toString();
}
function connectWs() {
    if (ws) return; // already connected or connecting
    try {
        ws = new WebSocket(wsUrl());
        ws.binaryType = "arraybuffer";
        ws.onopen = () => {
            S.wsOpen = true;
        };
        ws.onclose = () => {
            ws = null;
            S.wsOpen = false;
            setTimeout(connectWs, 1500);
        };
        ws.onerror = () => {
            ws = null;
            S.wsOpen = false;
        };
        ws.onmessage = (ev) => {
            try {
                const d = JSON.parse(ev.data);
                if (d.type === "state") {
                    S.snap = d;
                    S.presets = d.presets || S.presets;
                    renderState();
                    renderPresets();
                    if (d.doctor && !same(d.doctor, S.doctor)) {
                        S.doctor = d.doctor;
                        renderDoctor();
                    }
                    // logs come via HTTP polling still; only state is pushed over WS
                } else if (d.type === "pong") {
                    // heartbeat response, nothing to do
                }
            } catch (e) {
                /* ignore bad WS messages */
            }
        };
    } catch (e) {
        ws = null;
        S.wsOpen = false;
        setTimeout(connectWs, 1500);
    }
}

let polling = false;
async function poll() {
    if (polling) return;
    polling = true;
    try {
        const d = await api("/api/state?since=" + S.logSeq);
        S.snap = d;
        S.presets = d.presets;
        if (d.log.length) addLog(d.log);
        S.logSeq = d.log_seq;
        if (d.doctor && !same(d.doctor, S.doctor)) {
            S.doctor = d.doctor;
            renderDoctor();
        }
        if (!S.wsOpen) renderState(); // WS already pushed state if open
        renderPresets();
        $("#status").title = "";
    } catch (e) {
        if (!S.wsOpen) {
            // only show error if WS is not covering
            $("#status-text").textContent = e.message;
            $("#status").className = "status error";
        }
    } finally {
        polling = false;
    }
}

/* ---------------------------------------------------------------- start up */
async function init() {
    if (!TOKEN) {
        document.body.replaceChildren(
            el(
                "main",
                { style: "padding:40px;max-width:640px" },
                el("h2", {}, "Open Bluehour from the address it prints"),
                el(
                    "p",
                    {},
                    "Start the control panel with ",
                    el("code", {}, "bluehour-gui"),
                    ". It opens this page with a private key in the address.",
                ),
            ),
        );
        return;
    }
    try {
        S.schema = await api("/api/schema");
        const st = await api("/api/state");
        S.settings = st.settings;
        S.playlist = st.playlist;
        S.presets = st.presets;
        S.snap = st;
        S.doctor = st.doctor;
    } catch (e) {
        document.body.replaceChildren(
            el(
                "main",
                { style: "padding:40px;max-width:640px" },
                el("h2", {}, "Cannot reach Bluehour"),
                el("p", {}, e.message),
                el(
                    "p",
                    { class: "muted" },
                    "If this page was open for a long time, close it and start bluehour-gui again.",
                ),
            ),
        );
        return;
    }
    S.wsOpen = false;
    buildPanels();
    initPicker();
    initRemote();
    $("#btn-start").onclick = startPlayer;
    $("#btn-stop").onclick = stopPlayer;
    $("#btn-restart").onclick = startPlayer;
    $("#btn-quit").onclick = quit;
    let tab = "play";
    try {
        tab = sessionStorage.getItem("bh_tab") || "play";
    } catch (e) {
        /* ignore */
    }
    showTab(PANELS[tab] ? tab : "play");
    renderPlaylist();
    renderPresets();
    renderDoctor();
    connectWs();
    await poll();
    if (!S.doctor && !S.doctorAsked) {
        S.doctorAsked = true;
        guard(() => api("/api/tool", { tool: "doctor" }))();
    }
    setInterval(poll, 500);
}
init();
