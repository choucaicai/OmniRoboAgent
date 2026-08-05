#include "timer/hp_timer.h"

#include <iostream>
#include <sched.h>
#include <sys/epoll.h>
#include <sys/timerfd.h>

namespace rpp
{
    HPTimer::HPTimer(int interval, int priority, std::function<void(void *)> callback, void *arg)
        : active(false), interval(interval), priority(priority), registerCB(callback), callbackArg(arg), timerFd(-1)
    {
        pthread_attr_init(&attr);
    }
    HPTimer::HPTimer(int interval, int priority)
        : HPTimer(interval, priority, nullptr, nullptr) // 使用委托构造函数
    {
    }

    HPTimer::~HPTimer()
    {
        pthread_attr_destroy(&attr);

        if (active)
        {
            stop();
        }

        if (timerFd != -1)
        {
            close(timerFd);
        }
    }

    bool HPTimer::setInterval(int interval)
    {
        if (interval <= 0)
        {
            std::cout << "Timer interval must be greater than 0" << std::endl;
            return false;
        }

        if (timerFd != -1)
        {
            close(timerFd);
        }
        timerFd = timerfd_create(CLOCK_MONOTONIC, 0);
        if (timerFd == -1)
        {
            std::cout << "Failed to create timer" << std::endl;
            return false;
        }

        struct itimerspec its;
        its.it_value.tv_sec = interval / 1000;
        its.it_value.tv_nsec = (interval % 1000) * 1000000;
        its.it_interval.tv_sec = interval / 1000;
        its.it_interval.tv_nsec = (interval % 1000) * 1000000;

        if (timerfd_settime(timerFd, 0, &its, nullptr) == -1)
        {
            std::cout << "Failed to set timerfd" << std::endl;
            return false;
        }
        return true;
    }

    bool HPTimer::setPriority(int priority)
    {
        if (priority < 0 || priority > 99)
        {
            std::cout << "Timer priority must be greater than 0 and less than 100" << std::endl;
            return false;
        }

        struct sched_param param;
        param.sched_priority = priority;

        if (priority == 0)
        {
            pthread_attr_setschedpolicy(&attr, SCHED_OTHER); // 普通调度策略
        }
        else
        {
            pthread_attr_setschedpolicy(&attr, SCHED_FIFO); // 实时调度策略
        }
        pthread_attr_setschedparam(&attr, &param);
        pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
        return true;
    }

    void HPTimer::setCallback(std::function<void(void *)> callback, void *arg)
    {
        registerCB = callback;
        callbackArg = arg;
    }

    bool HPTimer::isActive() const { return active; }

    void HPTimer::start()
    {
        if (active)
        {
            std::cout << "Timer is already running" << std::endl;
            return;
        }

        if (!setInterval(interval))
        {
            std::cout << "Failed to set timer" << std::endl;
            return;
        }

        if (!setPriority(priority))
        {
            std::cout << "Failed to set priority" << std::endl;
            return;
        }

        if (pthread_create(&pThread, &attr, &HPTimer::threadEntry, this) != 0)
        {
            std::cout << "Failed to create thread" << std::endl;
        }
        active = true;
    }

    void HPTimer::stop()
    {
        if (!active)
        {
            std::cout << "Timer is already stopped" << std::endl;
            return;
        }
        active = false;
        pthread_join(pThread, nullptr);
    }

    void *HPTimer::threadEntry(void *arg)
    {
        auto self = static_cast<HPTimer *>(arg);
        self->threadFunction();
        return nullptr;
    }

    void HPTimer::threadFunction()
    {
        int epollFd = epoll_create1(0);
        if (epollFd == -1)
        {
            perror("epoll_create1");
            return;
        }

        struct epoll_event event;
        event.events = EPOLLIN;
        event.data.fd = timerFd;
        if (epoll_ctl(epollFd, EPOLL_CTL_ADD, timerFd, &event) == -1)
        {
            perror("epoll_ctl");
            close(epollFd);
            return;
        }

        while (active)
        {
            struct epoll_event events[1];
            int num_events = epoll_wait(epollFd, events, 1, -1);
            if (num_events == -1)
            {
                if (errno == EINTR)
                    continue; // 被信号中断
                perror("epoll_wait");
                break;
            }

            if (events[0].data.fd == timerFd)
            {
                uint64_t expirations;
                ssize_t s = read(timerFd, &expirations, sizeof(expirations));
                if (s != sizeof(expirations))
                {
                    perror("read");
                    break;
                }
                if (registerCB)
                {
                    registerCB(callbackArg);
                }
            }
        }

        close(epollFd);
    }
}