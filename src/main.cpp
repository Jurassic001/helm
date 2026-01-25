/**
 * @file main.cpp
 * @brief Headless vitals monitoring application for security threat assessment.
 * 
 * Outputs structured JSON to stdout for consumption by Python frontend.
 * Designed for 4K camera input with optimal positioning (doorbell/security camera).
 * 
 * Usage: ./helm_vitals --api_key <YOUR_API_KEY> [options]
 */

// stdlib includes
#include <string>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <chrono>
#include <mutex>

// third-party includes
#include <absl/status/status.h>
#include <absl/flags/flag.h>
#include <absl/flags/parse.h>
#include <absl/flags/usage.h>
#include <glog/logging.h>
#include <opencv2/highgui.hpp>
#include <physiology/modules/configuration.h>
#include <physiology/modules/messages/metrics.h>
#include <smartspectra/container/settings.hpp>
#include <smartspectra/container/configuration.hpp>
#include <smartspectra/video_source/camera/camera.hpp>
#include <smartspectra/container/foreground_container.hpp>
#include <google/protobuf/util/json_util.h>

namespace pcam = presage::camera;
namespace spectra = presage::smartspectra;
namespace settings = presage::smartspectra::container::settings;
namespace vs = presage::smartspectra::video_source;

// ================================ COMMAND LINE FLAGS ================================
// Camera/video source settings
// Note: WSL USB passthrough (usbipd) typically limits bandwidth to 1080p max.
// Use --video_url with Windows FFmpeg streaming for full 4K support.
ABSL_FLAG(int, camera_device_index, 0, "Camera device index (ignored if --video_url is set)");
ABSL_FLAG(int, capture_width_px, 1920, "Capture width (default 1080p for WSL compatibility)");
ABSL_FLAG(int, capture_height_px, 1080, "Capture height (default 1080p for WSL compatibility)");
ABSL_FLAG(pcam::CaptureCodec, codec, pcam::CaptureCodec::MJPG, "Video codec");

// Network video source (for Windows FFmpeg streaming)
ABSL_FLAG(std::string, video_url, "", "Video stream URL (e.g., tcp://localhost:5000). Overrides camera settings.");

// API settings
ABSL_FLAG(std::string, api_key, "", "SmartSpectra API key (required)");

// Processing settings
ABSL_FLAG(double, buffer_duration, 0.2, "Preprocessing buffer duration in seconds (0.2-1.0)");
ABSL_FLAG(int, verbosity, 1, "Verbosity level (0=errors only, 1=status, 2=metrics, 3=detailed)");

// Feature toggles
ABSL_FLAG(bool, enable_phasic_bp, false, "Enable phasic blood pressure computation (requires model)");
ABSL_FLAG(bool, enable_eda, false, "Enable electrodermal activity computation (requires model)");
ABSL_FLAG(bool, enable_micromotion, false, "Enable micromotion (requires thighs/knees visible)");
ABSL_FLAG(bool, enable_edge_metrics, true, "Enable real-time edge metrics");

// Debug options
ABSL_FLAG(bool, show_gui, false, "Show SmartSpectra debug GUI (disables headless mode)");

// ================================ JSON OUTPUT HELPERS ================================

/**
 * @brief Thread-safe JSON output to stdout
 */
class JsonOutputter {
public:
    void OutputJson(const std::string& json_type, const std::string& json_content) {
        std::lock_guard<std::mutex> lock(output_mutex_);
        std::cout << "{\"type\":\"" << json_type << "\",\"timestamp_ms\":" 
                  << GetTimestampMs() << ",\"data\":" << json_content << "}" << std::endl;
    }

    void OutputError(const std::string& error_message) {
        std::lock_guard<std::mutex> lock(output_mutex_);
        std::cout << "{\"type\":\"error\",\"timestamp_ms\":" << GetTimestampMs() 
                  << ",\"message\":\"" << EscapeJson(error_message) << "\"}" << std::endl;
    }

    void OutputStatus(int status_code, const std::string& description, int64_t frame_timestamp) {
        std::lock_guard<std::mutex> lock(output_mutex_);
        std::cout << "{\"type\":\"status\",\"timestamp_ms\":" << GetTimestampMs()
                  << ",\"data\":{\"code\":" << status_code 
                  << ",\"description\":\"" << EscapeJson(description) << "\""
                  << ",\"frame_timestamp\":" << frame_timestamp << "}}" << std::endl;
    }

private:
    std::mutex output_mutex_;

    int64_t GetTimestampMs() {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
    }

    std::string EscapeJson(const std::string& input) {
        std::string output;
        for (char c : input) {
            switch (c) {
                case '"': output += "\\\""; break;
                case '\\': output += "\\\\"; break;
                case '\n': output += "\\n"; break;
                case '\r': output += "\\r"; break;
                case '\t': output += "\\t"; break;
                default: output += c;
            }
        }
        return output;
    }
};

// Global outputter instance
JsonOutputter g_outputter;

// ================================ METRICS EXTRACTION ================================

/**
 * @brief Extract pulse metrics to JSON string
 * Note: SDK fields are RepeatedPtrField - we get the latest value from each
 */
std::string ExtractPulseJson(const presage::physiology::MetricsBuffer& metrics) {
    std::stringstream ss;
    ss << "{";
    bool first = true;
    
    if (metrics.has_pulse()) {
        const auto& pulse = metrics.pulse();
        
        // Heart rate (RepeatedPtrField<MeasurementWithConfidence>)
        if (!pulse.rate().empty()) {
            const auto& rate = *pulse.rate().rbegin();
            ss << "\"heart_rate\":{";
            ss << "\"value\":" << rate.value();
            ss << ",\"stable\":" << (rate.stable() ? "true" : "false");
            ss << ",\"confidence\":" << rate.confidence();
            ss << "}";
            first = false;
        }
        
        // Pulse trace (latest value for real-time display)
        if (!pulse.trace().empty()) {
            if (!first) ss << ",";
            const auto& latest = *pulse.trace().rbegin();
            ss << "\"trace_latest\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        // Strict pulse (high-precision)
        if (pulse.has_strict()) {
            if (!first) ss << ",";
            const auto& strict = pulse.strict();
            ss << "\"strict\":{";
            ss << "\"value\":" << strict.value();
            ss << "}";
            first = false;
        }
    }
    
    ss << "}";
    return ss.str();
}

/**
 * @brief Extract breathing metrics to JSON string
 */
std::string ExtractBreathingJson(const presage::physiology::MetricsBuffer& metrics) {
    std::stringstream ss;
    ss << "{";
    bool first = true;
    
    if (metrics.has_breathing()) {
        const auto& breathing = metrics.breathing();
        
        // Respiratory rate (RepeatedPtrField<MeasurementWithConfidence>)
        if (!breathing.rate().empty()) {
            const auto& rate = *breathing.rate().rbegin();
            ss << "\"respiratory_rate\":{";
            ss << "\"value\":" << rate.value();
            ss << ",\"stable\":" << (rate.stable() ? "true" : "false");
            ss << ",\"confidence\":" << rate.confidence();
            ss << "}";
            first = false;
        }
        
        // Upper trace (chest)
        if (!breathing.upper_trace().empty()) {
            if (!first) ss << ",";
            const auto& latest = *breathing.upper_trace().rbegin();
            ss << "\"chest_trace_latest\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        // Lower trace (abdomen)
        if (!breathing.lower_trace().empty()) {
            if (!first) ss << ",";
            const auto& latest = *breathing.lower_trace().rbegin();
            ss << "\"abdomen_trace_latest\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        // Apnea detection (RepeatedPtrField<DetectionStatus>)
        if (!breathing.apnea().empty()) {
            if (!first) ss << ",";
            const auto& apnea = *breathing.apnea().rbegin();
            ss << "\"apnea\":{";
            ss << "\"detected\":" << (apnea.detected() ? "true" : "false");
            ss << ",\"stable\":" << (apnea.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        // Amplitude (RepeatedPtrField<Measurement>)
        if (!breathing.amplitude().empty()) {
            if (!first) ss << ",";
            const auto& amp = *breathing.amplitude().rbegin();
            ss << "\"amplitude\":{";
            ss << "\"value\":" << amp.value();
            ss << ",\"stable\":" << (amp.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
    }
    
    ss << "}";
    return ss.str();
}

/**
 * @brief Extract blood pressure metrics to JSON string
 */
std::string ExtractBloodPressureJson(const presage::physiology::MetricsBuffer& metrics) {
    std::stringstream ss;
    ss << "{";
    
    if (metrics.has_blood_pressure()) {
        const auto& bp = metrics.blood_pressure();
        
        // Phasic blood pressure (RepeatedPtrField<MeasurementWithConfidence>)
        if (!bp.phasic().empty()) {
            const auto& phasic = *bp.phasic().rbegin();
            ss << "\"phasic\":{";
            ss << "\"value\":" << phasic.value();
            ss << ",\"stable\":" << (phasic.stable() ? "true" : "false");
            ss << ",\"confidence\":" << phasic.confidence();
            ss << "}";
        }
    }
    
    ss << "}";
    return ss.str();
}

/**
 * @brief Extract face detection metrics to JSON string
 */
std::string ExtractFaceJson(const presage::physiology::MetricsBuffer& metrics) {
    std::stringstream ss;
    ss << "{";
    bool first = true;
    
    if (metrics.has_face()) {
        const auto& face = metrics.face();
        
        // Blinking detection (RepeatedPtrField<DetectionStatus>)
        if (!face.blinking().empty()) {
            const auto& blink = *face.blinking().rbegin();
            ss << "\"blinking\":{";
            ss << "\"detected\":" << (blink.detected() ? "true" : "false");
            ss << ",\"stable\":" << (blink.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        // Talking detection (RepeatedPtrField<DetectionStatus>)
        if (!face.talking().empty()) {
            if (!first) ss << ",";
            const auto& talk = *face.talking().rbegin();
            ss << "\"talking\":{";
            ss << "\"detected\":" << (talk.detected() ? "true" : "false");
            ss << ",\"stable\":" << (talk.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        // Micro-expressions (RepeatedPtrField<MicroExpression>)
        if (!face.micro_expression().empty()) {
            if (!first) ss << ",";
            const auto& expr = *face.micro_expression().rbegin();
            ss << "\"micro_expression\":{";
            ss << "\"confidence\":" << expr.confidence();
            ss << ",\"stable\":" << (expr.stable() ? "true" : "false");
            ss << "}";
        }
    }
    
    ss << "}";
    return ss.str();
}

/**
 * @brief Extract edge metrics (real-time) to JSON string
 */
std::string ExtractEdgeMetricsJson(const presage::physiology::Metrics& metrics) {
    std::stringstream ss;
    ss << "{";
    bool first = true;
    
    // Edge breathing traces
    if (metrics.has_breathing()) {
        const auto& breathing = metrics.breathing();
        
        if (!breathing.upper_trace().empty()) {
            const auto& latest = *breathing.upper_trace().rbegin();
            ss << "\"chest_breathing\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        if (!breathing.lower_trace().empty()) {
            if (!first) ss << ",";
            const auto& latest = *breathing.lower_trace().rbegin();
            ss << "\"abdomen_breathing\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
    }
    
    // Micromotion
    if (metrics.has_micromotion()) {
        const auto& mm = metrics.micromotion();
        
        if (!mm.glutes().empty()) {
            if (!first) ss << ",";
            const auto& latest = *mm.glutes().rbegin();
            ss << "\"micromotion_glutes\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
        
        if (!mm.knees().empty()) {
            if (!first) ss << ",";
            const auto& latest = *mm.knees().rbegin();
            ss << "\"micromotion_knees\":{";
            ss << "\"value\":" << latest.value();
            ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
            ss << "}";
            first = false;
        }
    }
    
    // EDA (Electrodermal Activity - stress indicator)
    if (metrics.has_eda() && !metrics.eda().trace().empty()) {
        if (!first) ss << ",";
        const auto& latest = *metrics.eda().trace().rbegin();
        ss << "\"eda\":{";
        ss << "\"value\":" << latest.value();
        ss << ",\"stable\":" << (latest.stable() ? "true" : "false");
        ss << "}";
    }
    
    ss << "}";
    return ss.str();
}

// ================================ MAIN APPLICATION ================================

absl::Status RunVitalsMonitor(
    settings::Settings<settings::OperationMode::Continuous, settings::IntegrationMode::Rest>& settings,
    bool show_gui
) {
    spectra::container::CpuContinuousRestForegroundContainer container(settings);
    
    bool enable_edge_metrics = absl::GetFlag(FLAGS_enable_edge_metrics);
    int verbosity = absl::GetFlag(FLAGS_verbosity);

    // Video output callback - displays GUI when --show_gui is enabled
    if (show_gui) {
        MP_RETURN_IF_ERROR(container.SetOnVideoOutput(
            [](cv::Mat& output_frame, int64_t timestamp_milliseconds) -> absl::Status {
                cv::imshow("Helm Vitals Monitor", output_frame);
                // Process key events - 'q' or ESC to quit
                int key = cv::waitKey(1);
                if (key == 'q' || key == 27) {  // 'q' or ESC
                    return absl::CancelledError("User requested quit");
                }
                return absl::OkStatus();
            }
        ));
    }

    // Status change callback - outputs face positioning/lighting feedback
    MP_RETURN_IF_ERROR(container.SetOnStatusChange(
        [verbosity](presage::physiology::StatusValue status) -> absl::Status {
            g_outputter.OutputStatus(
                static_cast<int>(status.value()),
                presage::physiology::GetStatusDescription(status.value()),
                status.timestamp()
            );
            return absl::OkStatus();
        }
    ));

    // Core metrics callback - outputs processed vitals from cloud
    MP_RETURN_IF_ERROR(container.SetOnCoreMetricsOutput(
        [verbosity](
            const presage::physiology::MetricsBuffer& metrics_buffer,
            int64_t timestamp_milliseconds
        ) -> absl::Status {
            // Build comprehensive metrics JSON
            std::stringstream ss;
            ss << "{";
            ss << "\"frame_timestamp\":" << timestamp_milliseconds;
            ss << ",\"pulse\":" << ExtractPulseJson(metrics_buffer);
            ss << ",\"breathing\":" << ExtractBreathingJson(metrics_buffer);
            ss << ",\"blood_pressure\":" << ExtractBloodPressureJson(metrics_buffer);
            ss << ",\"face\":" << ExtractFaceJson(metrics_buffer);
            ss << "}";
            
            g_outputter.OutputJson("core_metrics", ss.str());
            
            // Also output raw protobuf JSON for debugging at high verbosity
            if (verbosity >= 3) {
                std::string raw_json;
                google::protobuf::util::JsonPrintOptions options;
                options.add_whitespace = false;
                google::protobuf::util::MessageToJsonString(metrics_buffer, &raw_json, options);
                g_outputter.OutputJson("core_metrics_raw", raw_json);
            }
            
            return absl::OkStatus();
        }
    ));

    // Edge metrics callback - outputs real-time local metrics
    // Note: SDK requires timestamp parameter in callback signature
    if (enable_edge_metrics) {
        MP_RETURN_IF_ERROR(container.SetOnEdgeMetricsOutput(
            [verbosity](const presage::physiology::Metrics& metrics, int64_t input_timestamp) {
                std::string edge_json = ExtractEdgeMetricsJson(metrics);
                g_outputter.OutputJson("edge_metrics", edge_json);
                
                // Raw output at high verbosity
                if (verbosity >= 3) {
                    std::string raw_json;
                    google::protobuf::util::JsonPrintOptions options;
                    options.add_whitespace = false;
                    google::protobuf::util::MessageToJsonString(metrics, &raw_json, options);
                    g_outputter.OutputJson("edge_metrics_raw", raw_json);
                }
                
                return absl::OkStatus();
            }
        ));
    }

    // Initialize and run
    MP_RETURN_IF_ERROR(container.Initialize());
    
    // Output startup message
    g_outputter.OutputJson("system", "{\"event\":\"initialized\",\"message\":\"Vitals monitoring started\"}");
    
    MP_RETURN_IF_ERROR(container.Run());
    
    return absl::OkStatus();
}

int main(int argc, char** argv) {
    // Disable stdout buffering for real-time JSON output to Python
    // When stdout is piped, C++ stdlib defaults to 4KB block buffering
    // This ensures each JSON line is immediately available to the reader
    setvbuf(stdout, NULL, _IONBF, 0);
    
    // Suppress SDK internal warnings (one_euro_filter timestamp warnings)
    // Must be set BEFORE InitGoogleLogging()
    // 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
    FLAGS_minloglevel = 2;  // Only show ERROR and FATAL
    
    google::InitGoogleLogging(argv[0]);
    
    absl::SetProgramUsageMessage(
        "Helm Vitals Monitor - Security threat assessment via physiological metrics.\n"
        "Outputs structured JSON to stdout for consumption by Python frontend.\n\n"
        "Usage: ./helm_vitals --api_key <YOUR_API_KEY> [options]\n\n"
        "JSON output types:\n"
        "  status       - Face positioning, lighting feedback (StatusCode)\n"
        "  core_metrics - Processed vitals from cloud (pulse, breathing, BP, face)\n"
        "  edge_metrics - Real-time local metrics (breathing traces, EDA)\n"
        "  error        - Error messages\n"
        "  system       - System events (initialized, shutdown)\n\n"
        "Video source options:\n"
        "  --video_url  - Stream URL (e.g., tcp://localhost:5000) for FFmpeg input\n"
        "                 Use scripts/stream_camera.bat on Windows for 4K streaming\n"
        "  Default: Direct camera at 1080p (WSL USB passthrough limitation)\n\n"
        "Debug options:\n"
        "  --show_gui   - Show SmartSpectra debug GUI (default: headless)\n"
    );
    absl::ParseCommandLine(argc, argv);
    
    // Validate API key
    std::string api_key = absl::GetFlag(FLAGS_api_key);
    if (api_key.empty()) {
        // Try environment variable
        const char* env_key = std::getenv("SMARTSPECTRA_API_KEY");
        if (env_key) {
            api_key = env_key;
        } else {
            g_outputter.OutputError("API key required. Use --api_key or set SMARTSPECTRA_API_KEY");
            return EXIT_FAILURE;
        }
    }

    // Build settings
    settings::Settings<settings::OperationMode::Continuous, settings::IntegrationMode::Rest> app_settings{};
    
    // Video source settings
    std::string video_url = absl::GetFlag(FLAGS_video_url);
    if (!video_url.empty()) {
        // Use network stream (from Windows FFmpeg)
        app_settings.video_source.input_video_path = video_url;
        g_outputter.OutputJson("system", 
            "{\"event\":\"video_source\",\"type\":\"stream\",\"url\":\"" + video_url + "\"}");
    } else {
        // Use local camera device
        app_settings.video_source.device_index = absl::GetFlag(FLAGS_camera_device_index);
        app_settings.video_source.capture_width_px = absl::GetFlag(FLAGS_capture_width_px);
        app_settings.video_source.capture_height_px = absl::GetFlag(FLAGS_capture_height_px);
        app_settings.video_source.codec = absl::GetFlag(FLAGS_codec);
        app_settings.video_source.auto_lock = false;  // Disable auto exposure lock for better compatibility
    }
    
    // General settings
    app_settings.headless = !absl::GetFlag(FLAGS_show_gui);  // Show GUI if --show_gui is set
    app_settings.interframe_delay_ms = 33;  // ~30 FPS to match camera frame rate
    app_settings.start_with_recording_on = true;  // Start immediately
    app_settings.scale_input = true;
    app_settings.binary_graph = true;
    if (absl::GetFlag(FLAGS_enable_phasic_bp)) {
        app_settings.enable_phasic_bp = true;
    }
    if (absl::GetFlag(FLAGS_enable_eda)) {
        app_settings.enable_eda = true;
    }
    if (absl::GetFlag(FLAGS_enable_micromotion)) {
        app_settings.enable_micromotion = true;
    }
    app_settings.enable_edge_metrics = absl::GetFlag(FLAGS_enable_edge_metrics);
    app_settings.verbosity_level = absl::GetFlag(FLAGS_verbosity);
    
    // Continuous mode settings
    app_settings.continuous.preprocessed_data_buffer_duration_s = absl::GetFlag(FLAGS_buffer_duration);
    
    // REST API settings
    app_settings.integration.api_key = api_key;

    bool show_gui = absl::GetFlag(FLAGS_show_gui);
    absl::Status status = RunVitalsMonitor(app_settings, show_gui);

    if (!status.ok()) {
        g_outputter.OutputError(std::string(status.message()));
        return EXIT_FAILURE;
    }
    
    g_outputter.OutputJson("system", "{\"event\":\"shutdown\",\"message\":\"Vitals monitoring stopped\"}");
    return 0;
}
