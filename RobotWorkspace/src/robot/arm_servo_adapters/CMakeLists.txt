cmake_minimum_required(VERSION 3.10)
project(arm_servo_adapters)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_BUILD_TYPE Debug)
# set(EXECUTABLE_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/bin)

# O3优化
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3")
# 串口定义,适用于22.04（没有定义该宏会导致recv time out）
add_definitions(-DSERIAL_NEW_CUSTOMBAUDRATE)

option(ENABLE_FRANKA "Enable Franka support" ON)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(fastcdr REQUIRED)
find_package(Eigen3 REQUIRED)
# 设置zenoh本地路径
set(ZENOHC_ROOT "${CMAKE_SOURCE_DIR}/interfaces/zenoh-c")
set(ZENOHCXX_ROOT "${CMAKE_SOURCE_DIR}/interfaces/zenohcpp")

find_package(zenohc REQUIRED
    HINTS "${ZENOHC_ROOT}/lib/cmake/zenohc"
)
find_package(zenohcxx REQUIRED 
    HINTS "${ZENOHCXX_ROOT}/lib/cmake/zenohcxx"
)

if(ENABLE_FRANKA)
  find_package(pinocchio REQUIRED)
  add_definitions(-DFRANKA_ARM)
  set(ARM_SDK_PATH "${CMAKE_SOURCE_DIR}/interfaces/Franka")
  message(STATUS "== Franka SDK path: ${ARM_SDK_PATH}")
  set(ARM_INCLUDE_DIRS  "${ARM_SDK_PATH}/include")
  set(ARM_LINK_LIBS "/home/rpp/3rdparty/libfranka/v0.13-build/libfranka.so.0.13")
  if(UNIX)
    add_definitions(-D_OS_UNIX)
  endif()
endif()

include_directories(
  include
  ${ARM_INCLUDE_DIRS}
  ${EIGEN3_INCLUDE_DIRS}
)

link_directories(${ARM_LIB_DIRS})

add_executable(master_arm 
    src/master_arm.cpp 
    $<$<BOOL:${ENABLE_FRANKA}>:src/arm/arm_franka.cpp>

)
target_link_libraries(master_arm 
    zenohcxx::zenohc
    ${ARM_LINK_LIBS}
    nlohmann_json::nlohmann_json
    fastcdr
)
set_target_properties(master_arm PROPERTIES
    BUILD_WITH_INSTALL_RPATH TRUE
    INSTALL_RPATH "${CMAKE_SOURCE_DIR}/interfaces/zenoh-c/lib"
)

add_executable(slave_arm
    src/slave_arm.cpp 
    src/timer/hp_timer.cpp
    $<$<BOOL:${ENABLE_FRANKA}>:src/arm/arm_franka.cpp>
)

target_link_libraries(slave_arm 
    ${ARM_LINK_LIBS}
    yaml-cpp
    zenohcxx::zenohc
    nlohmann_json::nlohmann_json
    fastcdr
)
install(TARGETS master_arm slave_arm
    DESTINATION lib/${PROJECT_NAME}
)

ament_target_dependencies(master_arm
  rclcpp
  sensor_msgs
  std_msgs
)
ament_target_dependencies(slave_arm
  rclcpp
  sensor_msgs
  std_msgs
)

ament_package()