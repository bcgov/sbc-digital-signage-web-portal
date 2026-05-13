function stopPreview(preview) {
    preview.pause();
    preview.src = "";
    preview.load();
}

function formatCountdown(millisecondsRemaining) {
    const totalSeconds = Math.max(0, Math.ceil(millisecondsRemaining / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

const uploadArea = document.getElementById("uploadArea");
const videoInput = document.getElementById("videoInput");
const preview = document.getElementById("preview");
const previewSection = document.getElementById("previewSection");
const previewPlaceholder = document.getElementById("previewPlaceholder");
const selectedFileLabel = document.getElementById("selectedFileLabel");
const confirmBtn = document.getElementById("confirmBtn");
const currentVideo = document.getElementById("currentVideo");
const successMsg = document.getElementById("successMsg");

const defaultFilePrompt = "Click to select a video file to upload";

let selectedFile = null;
let previewObjectUrl = null;

function resetNewVideoState() {
    if (previewObjectUrl) {
        URL.revokeObjectURL(previewObjectUrl);
        previewObjectUrl = null;
    }

    stopPreview(preview);
    previewSection.classList.add("hidden");
    previewPlaceholder.classList.remove("hidden");
    selectedFileLabel.textContent = defaultFilePrompt;
    videoInput.value = "";
    selectedFile = null;
}

if (
    uploadArea &&
    videoInput &&
    preview &&
    previewSection &&
    previewPlaceholder &&
    selectedFileLabel &&
    confirmBtn &&
    successMsg
) {
    uploadArea.addEventListener("click", (event) => {
        if (event.target.closest("label[for='videoInput']")) {
            return;
        }

        videoInput.click();
    });

    videoInput.addEventListener("change", (event) => {
        const [file] = event.target.files;
        if (!file) {
            return;
        }

        selectedFile = file;
        if (previewObjectUrl) {
            URL.revokeObjectURL(previewObjectUrl);
        }
        previewObjectUrl = URL.createObjectURL(file);
        preview.src = previewObjectUrl;
        preview.addEventListener(
            "loadedmetadata",
            () => {
                preview.currentTime = 3;
            },
            { once: true },
        );

        previewSection.classList.remove("hidden");
        previewPlaceholder.classList.add("hidden");
        selectedFileLabel.textContent = file.name;
        successMsg.classList.add("hidden");
    });

    confirmBtn.addEventListener("click", async () => {
        if (!selectedFile) {
            return;
        }

        confirmBtn.disabled = true;
        confirmBtn.textContent = "Uploading... Please wait";

        const formData = new FormData();
        formData.append("video", selectedFile);

        try {
            const response = await fetch("/upload", {
                method: "POST",
                body: formData,
            });
            const data = await response.json();

            if (response.ok) {
                successMsg.classList.remove("hidden");
                resetNewVideoState();
                if (currentVideo) {
                    currentVideo.pause();
                    currentVideo.src = `/current-video?ts=${Date.now()}`;
                    currentVideo.load();
                    void currentVideo.play().catch(() => {});
                }
            } else {
                alert("Upload failed: " + (data.error || "Unknown error"));
            }
        } catch (error) {
            alert("Upload error: " + error.message);
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.textContent = "Confirm & Upload Video";
        }
    });
}

const restartBtn = document.getElementById("restartBtn");
if (restartBtn) {
    restartBtn.addEventListener("click", async () => {
        if (
            !window.confirm(
                "Are you sure you want to restart the TV? The Raspberry Pi will reboot and this page will become unavailable for about 1-2 minutes. Please reconnect to the TV Wi-Fi network after rebooting.",
            )
        ) {
            return;
        }

        restartBtn.disabled = true;
        restartBtn.textContent = "Restarting Now...";

        const restartDurationMs = 3 * 60 * 1000;
        const restartStartedAt = Date.now();

        document.body.innerHTML = `
        <div class="restart-state">
            <div class="restart-card">
                <div class="restart-icon">🔄</div>
                <h2>TV Restarting</h2>
                <p>The Raspberry Pi is rebooting now. This page will refresh automatically in 3 minutes.</p>
                <div class="progress progress--restart" role="progressbar" aria-label="Restart progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
                    <div class="progress__bar" id="restartProgressBar"></div>
                </div>
                <p class="restart-countdown">Time remaining: <strong id="restartCountdown">3:00</strong></p>
                <p class="text-small">If the TV is already back online before then, you can also refresh this page manually.</p>
            </div>
        </div>
    `;

        const restartProgress = document.getElementById("restartProgressBar");
        const restartCountdown = document.getElementById("restartCountdown");
        const restartProgressContainer = restartProgress?.parentElement;

        const updateRestartState = () => {
            const elapsedMs = Date.now() - restartStartedAt;
            const percentComplete = Math.min(100, (elapsedMs / restartDurationMs) * 100);
            const remainingMs = Math.max(0, restartDurationMs - elapsedMs);

            if (restartProgress) {
                restartProgress.style.width = `${percentComplete}%`;
            }

            if (restartProgressContainer) {
                restartProgressContainer.setAttribute("aria-valuenow", String(Math.round(percentComplete)));
            }

            if (restartCountdown) {
                restartCountdown.textContent = formatCountdown(remainingMs);
            }

            if (elapsedMs >= restartDurationMs) {
                window.clearInterval(restartInterval);
                window.location.reload();
            }
        };

        updateRestartState();
        const restartInterval = window.setInterval(updateRestartState, 250);

        try {
            await fetch("/restart", { method: "POST" });
        } catch (error) {
            // The app is expected to become unavailable during reboot.
        }
    });
}
