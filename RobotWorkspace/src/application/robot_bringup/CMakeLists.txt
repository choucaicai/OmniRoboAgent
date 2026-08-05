cmake_minimum_required(VERSION 3.5)
project(robot_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY
  launch
  maps
  params
  rviz
  DESTINATION share/${PROJECT_NAME})

ament_package()