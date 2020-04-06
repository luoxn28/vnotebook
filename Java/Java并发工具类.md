---
layout: blog
title: Java并发工具类
date: 2020-02-29 17:30:28
categories: [Java]
tags: [多线程]
toc: true
comments: true
---

Java并发工具类主要有CyclicBarrier、CountDownLatch、Semaphore和Exchanger，日常开发中经常使用的是CountDownLatch和Semaphore。下面就简单分析下这几个并发工具类：

### CyclicBarrier 内存屏障

CyclicBarrier底层借助于一个count计数器和Lock/Condition实现内存内存屏障功能，在对count--时必须先获取到lock，如果count不为0，则调用condition.wait进行阻塞操作；直到当count为0时，执行barrierCommand(如果配置的话，执行barrierCommand的线程是刚好将count减到0的那个线程)，然后调用condition.signalAll唤醒所有等待的线程。

> CyclicBarrier可用于多线程同步、多线程计算最后合并计算结果的场景，比如分片计算最后使用CyclicBarrier统计最后的结果等。

CyclicBarrier使用示例如下：

```java
public static void main(String[] args) throws Exception {
    CyclicBarrier barrier = new CyclicBarrier(2, 
            () -> System.out.println(Thread.currentThread().getName() + ": all is ok"));
    Runnable task = () -> {
        try {
            System.out.println(Thread.currentThread().getName() + ": start wait");
            barrier.await();
            System.out.println(Thread.currentThread().getName() + ": start ok");
        } catch (Exception e) {
            e.printStackTrace();
        }
    };
    
    Thread t1 = new Thread(task, "thread1");
    Thread t2 = new Thread(task, "thread2");
    t2.start();
    t1.start();
    t1.join();
    t2.join();
}
```

### CountDownLatch 计数器

CountDownLatch允许一个或多个线程等待其他线程完成操作。CountDownLatch底层借助于AQS来实现功能，初始化一个CountDownLatch(n)时，相当于创建了一个state为n的AQS，当调用countDown()时会对AQS进行减一操作，如果state为0，则会对阻塞队列中所有线程进行唤醒操作。

CountDownLatch计数器必须大于等于0，等于0的时候调用await方法时不会阻塞当前线程，注意CountDownLatch不可能重新初始化或者修改CountDownLatch对象的内部计数的值。一个线程调用coundDown方法happen-before，另一个线程调用await方法。

```java
public static void main(String[] args) throws Exception {
    CountDownLatch downLatch = new CountDownLatch(2);
    Runnable task = () -> {
        try {
            System.out.println(Thread.currentThread().getName() + ": start countDown");
            downLatch.countDown();
            System.out.println(Thread.currentThread().getName() + ": start ok");
        } catch (Exception e) {
            e.printStackTrace();
        }
    };

    Thread t1 = new Thread(task, "thread1");
    Thread t2 = new Thread(task, "thread2");
    t1.start();
    t2.start();

    downLatch.await();
    System.out.println("main wait ok");

    t1.join();
    t2.join();
}
```

### Semaphore信号量

Semaphore用来控制同时访问特定资源的线程数量，它通过协调各个线程，保证合理的使用公共资源。Semaphore可用作流量控制，特别是公共资源有限的应用场景，比如数据库连接。

Semaphore底层也是基于AQS，初始化Semaphore(n)相当于初始化一个state为n的AQS，调用acquire()时会对进行state - 1操作，如果结果大于0则CAS设置state为state-1，相当于获取到了信号量，否则进行阻塞操作（调用tryAcquire则不会阻塞线程）。调用release会对state进行++操作。

```java
public static void main(String[] args) {
    Semaphore semaphore = new Semaphore(2);
    ExecutorService executor = Executors.newFixedThreadPool(10);

    Runnable task = () -> {
        try {
            System.out.println(Thread.currentThread().getName() + " acquire before");
            semaphore.acquire();
            System.out.println(Thread.currentThread().getName() + " acquire ok");
            semaphore.release();
        } catch (InterruptedException e) {
            e.printStackTrace();
        }
    };

    executor.execute(task);
    executor.execute(task);
    executor.execute(task);
    executor.execute(task);
}
```

### Exchanger 线程间交换数据

Exchanger是一个用户线程间交换数据的工具类，它提供了一个同步点，在这个同步点上，两个线程可以交换彼此的数据。这两个线程通过exchange方法交换数据，如果第一个线程先执行exchange方法，他会一直等待第二个线程也执行exchange方法，当两个线程都达到同步点时，这两个线程交换数据，将本线程产生的数据传递给对方。

```java
public static void main(String[] args) {
    Exchanger<String> exchanger = new Exchanger<>();
    Runnable task = () -> {
        try {
            String result = exchanger.exchange(Thread.currentThread().getName());
            System.out.println(Thread.currentThread().getName() + ": " + result);
        } catch (InterruptedException e) {
            e.printStackTrace();
        }
    };

    ExecutorService executor = Executors.newFixedThreadPool(2);
    executor.execute(task);
    executor.execute(task);
}
```

#### Exchanger实现分析

Exchanger算法的核心是通过一个可交换数据的slot，以及一个可以带有数据item的参与者，slot是Node类型，Node定义如下：

```java
@sun.misc.Contended static final class Node {
    int index;              // Arena index
    int bound;              // Last recorded value of Exchanger.bound
    int collides;           // Number of CAS failures at current bound
    int hash;               // Pseudo-random for spins
    Object item;            // This thread's current item
    volatile Object match;  // Item provided by releasing thread
    volatile Thread parked; // Set to this thread when parked, else null
}

static final class Participant extends ThreadLocal<Node> {
    public Node initialValue() { return new Node(); }
}
```

每一个参与者都带有一个Participant，当调用exchange时，如果slot为空，则将自己携带的数据CAS设置到slot上，然后park自己；如果slot不为空，则表示已经有线程在slot里设置了数据，则读取Node.item字段，并将自己携带的数据设置到Node.match字段，然后唤醒之前设置数据的线程（之前阻塞的线程在唤醒后读取Node.match字段返回），然后返回数据即可。