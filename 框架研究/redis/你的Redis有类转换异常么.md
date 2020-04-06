---
layout: blog
title: 你的Redis有类转换异常么
date: 2019-06-03 12:50:06
categories: [框架研究]
tags: [redis,线上问题]
toc: true
comments: true
---

之前同事反馈说线上遇到Redis反序列化异常问题，异常如下：
```java
XxxClass1 cannot be cast to XxxClass2
```
已知信息如下：
*   该异常不是必现的，偶尔才会出现；
*   出现该异常后重启应用或者过一会就好了；
*   序列化协议使用了hessian。

因为偶尔出现，首先看了报异常那块业务逻辑是不是有问题，看了一遍也发现什么问题。看了下对应日志，发现是在Redis读超时之后才出现的该异常，因此怀疑redis client操作逻辑那块导致的（公司架构组对redis做了一层封装），发现获取/释放redis连接如下代码：
```java
try {
    jedis = jedisPool.getResource();
    // jedis业务读写操作
} catch (Exception e) {
    // 异常处理
} finally {
    if (jedis != null) {
        // 归还给连接池
        jedisPool.returnResourceObject(jedis);
    }
}
```
初步认定原因为：发生了读写超时的连接，直接归还给连接池，下次使用该连接时读取到了上一次Redis返回的数据。因此本地验证下，示例代码如下：
```java
@Data
@NoArgsConstructor
@AllArgsConstructor
static class Person implements Serializable {
    private String name;
    private int age;
}
@Data
@NoArgsConstructor
@AllArgsConstructor
static class Dog implements Serializable {
    private String name;
}

public static void main(String[] args) throws Exception {
    JedisPoolConfig config = new JedisPoolConfig();
    config.setMaxTotal(1);
    JedisPool jedisPool = new JedisPool(config, "192.168.193.133", 6379, 2000, "123456");
    
    Jedis jedis = jedisPool.getResource();
    jedis.set("key1".getBytes(), serialize(new Person("luoxn28", 26)));
    jedis.set("key2".getBytes(), serialize(new Dog("tom")));
    jedisPool.returnResourceObject(jedis);
    
    try {
        jedis = jedisPool.getResource();
        Person person = deserialize(jedis.get("key1".getBytes()), Person.class);
        System.out.println(person);
    } catch (Exception e) {
        // 发生了异常之后，未对该连接做任何处理
        System.out.println(e.getMessage());
    } finally {
        if (jedis != null) {
            jedisPool.returnResourceObject(jedis);
        }
    }
    
    try {
        jedis = jedisPool.getResource();
        Dog dog = deserialize(jedis.get("key2".getBytes()), Dog.class);
        System.out.println(dog);
    } catch (Exception e) {
        System.out.println(e.getMessage());
    } finally {
        if (jedis != null) {
            jedisPool.returnResourceObject(jedis);
        }
    }
}
```
连接超时时间设置2000ms，为了方便测试，可以在redis服务器上使用gdb命令断住redis进程（如果redis部署在Linux系统上），比如在执行 `jedis.get("key1".getBytes()` 代码前，对redis进程使用gdb命令断住，那么就会导致读取超时，然后就会触发如下异常：
```
Person cannot be cast to Dog
```
既然已经知道了该问题原因并且本地复现了该问题，对应解决方案是，在发生异常时归还给连接池时关闭该连接即可(*jedis.close*内部已经做了判断)，代码如下：
```java
try {
    jedis = jedisPool.getResource();
    // jedis业务读写操作
} catch (Exception e) {
    // 异常处理
} finally {
    if (jedis != null) {
        // 归还给连接池
        jedis.close();
    }
}
```

至此，该问题解决。注意，因为使用了hessian序列化（其包含了类型信息，类似的有Java本身序列化机制），所有会报类转换异常；如果使用了json序列化（其只包含对象属性信息），反序列化时不会报异常，只不过因为不同类的属性不同，会导致反序列化后的对象属性为空或者属性值混乱，使用时会导致问题，并且这种问题因为没有报异常所以更不容易发现。

既然说到了Redis的连接，要知道的是，Redis基于`RESP(Redis Serialization Protocol)`协议来通信，并且通信方式是停等方式，也就说一次通信独占一个连接直到client读取到返回结果之后才能释放该连接让其他线程使用。小伙伴们可以思考一下，Redis通信能否像dubbo那样使用`单连接+序列号（标识单次通信）`通信方式呢？理论上是可以的，不过由于RESP协议中并没有一个"序列号"的字段，所以直接靠原生的通信方法来实现是不现实的。不过我们可以通过echo命令传递并返回"序列号"+正常的读写方式来实现，这里要保证二者执行的原子性，可以通过lua脚本或者事务来实现，事务方式如下：
```
MULTI
ECHO "唯一序列号"
GET key1
EXEC
```
然后客户端收到的结果是一个 `[ "唯一序列号", "value1" ]`的列表，你可以根据前一项识别出这是你哪个线程发送的请求。

为什么Redis通信方式并没有采用类似于dubbo这种通信方式呢，个人认为有以下几点：
* 使用停等这种通信方式实现简单，并且协议字段尽可能紧凑；
* Redis都是内存操作，处理性能较强，停等协议不会造成客户端等待时间较长；
* 目前来看，通信方式这块不是Redis使用上的性能瓶颈，这一点很重要。
