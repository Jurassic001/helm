cmake_minimum_required(VERSION 3.27.0)
project(HelmVitals CXX)
 
# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
 
# Find required packages
find_package(SmartSpectra REQUIRED)
find_package(OpenCV REQUIRED)

# ============== helm_vitals (headless JSON output for Python integration) ==============
add_executable(helm_vitals main.cpp)

target_link_libraries(helm_vitals
    SmartSpectra::Container
    ${OpenCV_LIBS}
)
