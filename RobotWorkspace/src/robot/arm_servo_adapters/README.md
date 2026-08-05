# 遥操作控制器
用于遥操作控制，使用飞特舵机。
## 编译安装
```
mkdir build
cd build
cmake ..
make
```
不同机械臂类型通过宏定义控制  
[franka机械臂角度范围比较特殊](https://franka.cn/FCI/control_parameters.html#limits-for-franka-research-3),部分关节角度无法到达0度，角度运动范围小于360，因此存在软件限位，并且主臂零位对应实际从臂零位为：[0, 0, 0, -3 * M_PI_4, 0, M_PI_2, M_PI_4]）  
A1，A3：-166到166  
A2：-105到105  
A4: -176到-7  
A5：-165到165  
A6：25到265  
A7：-175到175  
franka外部依赖
```
sudo apt-get install -y build-essential cmake git libpoco-dev libeigen3-dev libfmt-dev
```
Pinocchio
## joycon
python依赖  
```
cd scripts
pip install -r requirements.txt
```
配置udev规则  
joycon  
```
sudo vim /etc/udev/rules.d/50-nintendo-switch.rules
```
添加以下内容  
```
# Switch Joy-con (L) (Bluetooth only)
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", KERNELS=="0005:057E:2006.*", MODE="0666"

# Switch Joy-con (R) (Bluetooth only)
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", KERNELS=="0005:057E:2007.*", MODE="0666"

# Switch Pro controller (USB and Bluetooth)
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="2009", MODE="0666"
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", KERNELS=="0005:057E:2009.*", MODE="0666"

# Switch Joy-con charging grip (USB only)
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="200e", MODE="0666"

KERNEL=="js0", SUBSYSTEM=="input", MODE="0666"
```  
舵机臂  
```
sudo vim /etc/udev/rules.d/99-servo.rules
```
添加以下内容
```
KERNEL=="ttyUSB*", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", MODE="0666", SYMLINK+="master_arm"
```

更新udev规则  
```
sudo udevadm control --reload-rules && sudo udevadm trigger
```
其他依赖  
```
sudo apt-get install libhidapi-hidraw0
```
## 配置
配置示例在config/servo_config.yaml中。
id: 舵机id （对应飞特舵机地址） 
dir: 舵机方向，1为正转，-1为反转  
offset: 舵机偏移量(通过初始标定获得)
init_position: 舵机初始位置  

```
axes:
  - id: 1
    dir: 1
    offset: -72.0703125
    init_position: -0.263671875
  - id: 2
    dir: -1
    offset: 48.0761719
    init_position: 5.18554688
  - id: 3
    dir: 1
    offset: 47.1972656
    init_position: -91.9335938
  - id: 4
    dir: 1
    offset: -39.2871094
    init_position: -4.21875
  - id: 5
    dir: 1
    offset: -156.621094
    init_position: -77.2558594
  - id: 6
    dir: 1
    offset: -67.4121094
    init_position: -14.4140625
```
## 运行
### 准备工作：
主臂第一次运行需要手动校准，校准后会自动更新配置文件。
```
./master_arm -C
```
运行上述程序后，根据提示将各个舵机旋转到对应位置，然后按Enter键保存配置。所有关节较准完成后自动退出。  

### 使用
1. 启动主臂（主臂第一次运行需要手动校准，校准后会自动更新配置文件。）    
```
./master_arm [options]  
Options:  
  -C, --calibrate       启动时执行手动校准  
  -s, --serial <number> 串口设备路径 (默认: /dev/ttyUSB0)
  -c, --config <path>   配置文件路径 (默认: ~/rpp_data/config/servo_config.yaml)  
  -i, --ip <address>    UDP IP地址 (默认: 127.0.0.1)
  -p, --port <number>   UDP端口号 (默认: 12345)
  -h, --help            显示帮助信息
```


2. 启动从臂
```
Usage: ./slave_arm [options]
Options:
  -s, --server-ip <address>  UDP IP地址 (默认: 127.0.0.1)
  -p, --port <number>        UDP端口号 (默认: 12345)
  -a, --arm-ip <address>    机械臂IP地址 (默认: 192.168.1.10)
  -t, --arm-port <number>   机械臂控制端口 (默认: 10000)
  -r, --arm-rt-port <number> 机械臂实时端口 (默认: 10001)
  -T, --period <ms>         控制周期（毫秒） (默认: 1)
  -j, --joints <number>     机械臂关节数 (默认: 6)
  -h, --help                显示帮助信息
```
3. 启动joycon
```
cd scripts
python3 joycon.py
```
joycon 的按键功能如下：  
ZL、ZR：夹爪开合  
plus、minus：主臂上下使能  
home、capture：主臂复位（回到初始位置）  
y,right:设置主臂当前位置为初始位置  
4. 启动夹爪
```
cd scripts
python3 endeffector_controller.py
```
### zenoh to ros2 
1. 依赖安装

```
echo "deb [trusted=yes] https://download.eclipse.org/zenoh/debian-repo/ /" | sudo tee -a /etc/apt/sources.list > /dev/null
sudo apt update
sudo apt install zenoh-plugin-dds
sudo apt install zenoh-bridge-dds

sudo apt install ros-humble-rmw-cyclonedds-cpp
sudo apt install ros-humble-cyclonedds
```

```
sudo vim ~/.bashrc 
# 写入如下配置，NetworkInterface改为对应网络接口
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ROS_LOCALHOST_ONLY=1
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces>
                              <NetworkInterface name="wlp5s0" priority="default" multicast="true" />
                          </Interfaces></General></Domain></CycloneDDS>'

```
2. 启动zenoh-bridge-ros2dds
```
zenoh-bridge-ros2dds
```
3. 启动ros2 处理节点 接收数据（注意：如果没有节点订阅消息，无法通过 ros2 bag 录制或查看消息）

### Pinocchio 运动学求解
1. [安装Pinocchio](https://stack-of-tasks.github.io/pinocchio/download.html)




