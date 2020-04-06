---
layout: blog
title: ConcurrentHashMap竟然也有死循环
date: 2020-04-06 12:38:12
categories: [Java]
tags: []
toc: true
comments: true
---

---
title: ConcurrentHashMap竟然也有死循环
date: 2019-06-01 11:35:29
categories: [Java]
tags: []
toc: true
comments: true
---

> 前几天和拼多多及政采云的架构师们闲聊，其中拼多多架构师说遇到了一个ConcurrentHashMap死循环问题，当时心里想这不科学呀？ConcurrentHashMap怎么还有死循环呢，毕竟它已经解决HashMap中rehash中死循环问题了，但是随着深入的分析，发现事情并没有之前想的那么简单~ **(以下分析基于jdk版本：jdk1.8.0_171)**

保险起见，不能直接贴出出现问题的业务代码，因此将该问题简化成如下代码：

```java
ConcurrentHashMap<Integer, Integer> map = new ConcurrentHashMap<>();
// map默认capacity 16，当元素个数达到(capacity - capacity >> 2) = 12个时会触发rehash
for (int i = 0; i < 11; i++) {
    map.put(i, i);
}

map.computeIfAbsent(12, (k) -> {
    // 这里会导致死循环 :(
    map.put(100, 100);
    return k;
});

// 其他操作
```

感兴趣的小伙伴可以在电脑上运行下，话不说多，先说下问题原因：当执行`computeIfAbsent`时，如果key对应的slot为空，此时会创建`ReservationNode`对象(hash值为`RESERVED=-3`)放到当前slot位置，然后调用`mappingFunction.apply(key)`生成value，根据value创建Node之后赋值到slow位置，此时完成`computeIfAbsent`流程。但是上述代码`mappingFunction`中又对该map进行了一次put操作，并且触发了rehash操作，在`transfer`中遍历slot数组时，依次判断slot对应Node是否为null、hash值是否为MOVED=-1、hash值否大于0(list结构)、Node类型是否是TreeBin(红黑树结构)，唯独没有判断hash值为`RESERVED=-3`的情况，因此导致了死循环问题。

问题分析到这里，原因已经很清楚了，当时我们认为，这可能是jdk的`“bug”`，因此我们最后给出的解决方案是：

- 如果在rehash时出现了`slot`节点类型是`ReservationNode`，可以给个提示，比如抛异常；
- 理论上来说，`mappingFunction`中不应该再对当前map进行更新操作了，但是jdk并没有禁止不能这样用，最好说明下。

最后，另一个朋友看了`computeIfAbsent`的注释：

```java
/**
 * If the specified key is not already associated with a value,
 * attempts to compute its value using the given mapping function
 * and enters it into this map unless {@code null}.  The entire
 * method invocation is performed atomically, so the function is
 * applied at most once per key.  Some attempted update operations
 * on this map by other threads may be blocked while computation
 * is in progress, so the computation should be short and simple,
 * and must not attempt to update any other mappings of this map.
 */
public V computeIfAbsent(K key, Function<? super K, ? extends V> mappingFunction)
```

我们发现，其实人家已经知道了这个问题，还特意注释说明了。。。我们还是`too yong too simple`啊。至此，ConcurrentHashMap死循环问题告一段落，还是**要遵循编码规范，不要在mappingFunction中再对当前map进行更新操作**。其实ConcurrentHashMap死循环不仅仅出现在上述讨论的场景中，以下场景也会触发，原因和上述讨论的是一样的，代码如下，感兴趣的小伙伴也可以本地跑下：

```java
ConcurrentHashMap<Integer, Integer> map = new ConcurrentHashMap<>();
map.computeIfAbsent(12, (k) -> {
    map.put(k, k);
    return k;
});

System.out.println(map);
// 其他操作
```

最后，一起跟着`computeIfAbsent`源码来分下上述死循环代码的执行流程，限于篇幅，只分析下主要流程代码：

```java
public V computeIfAbsent(K key, Function<? super K, ? extends V> mappingFunction) {
    if (key == null || mappingFunction == null)
        throw new NullPointerException();
    int h = spread(key.hashCode());
    V val = null;
    int binCount = 0;
    for (Node<K,V>[] tab = table;;) {
        Node<K,V> f; int n, i, fh;
        if (tab == null || (n = tab.length) == 0)
            tab = initTable();
        else if ((f = tabAt(tab, i = (n - 1) & h)) == null) {
            Node<K,V> r = new ReservationNode<K,V>();
            synchronized (r) {
                // 这里使用synchronized针对局部对象意义不大，主要是下面的cas操作保证并发问题
                if (casTabAt(tab, i, null, r)) {
                    binCount = 1;
                    Node<K,V> node = null;
                    try {
                        // 这里的value返回可能为null呦
                        if ((val = mappingFunction.apply(key)) != null)
                            node = new Node<K,V>(h, key, val, null);
                    } finally {
                        setTabAt(tab, i, node);
                    }
                }
            }
            if (binCount != 0)
                break;
        }
        else if ((fh = f.hash) == MOVED)
            tab = helpTransfer(tab, f);
        else {
            boolean added = false;
            synchronized (f) {
                // 仅仅判断了node.hash >=0和node为TreeBin类型情况，未判断`ReservationNode`类型
                // 扩容时判断和此处类似
                if (tabAt(tab, i) == f) {
                    if (fh >= 0) {
                        binCount = 1;
                        for (Node<K,V> e = f;; ++binCount) {
                            K ek; V ev;
                            if (e.hash == h &&
                                ((ek = e.key) == key ||
                                 (ek != null && key.equals(ek)))) {
                                val = e.val;
                                break;
                            }
                            Node<K,V> pred = e;
                            if ((e = e.next) == null) {
                                if ((val = mappingFunction.apply(key)) != null) {
                                    added = true;
                                    pred.next = new Node<K,V>(h, key, val, null);
                                }
                                break;
                            }
                        }
                    }
                    else if (f instanceof TreeBin) {
                        binCount = 2;
                        TreeBin<K,V> t = (TreeBin<K,V>)f;
                        TreeNode<K,V> r, p;
                        if ((r = t.root) != null &&
                            (p = r.findTreeNode(h, key, null)) != null)
                            val = p.val;
                        else if ((val = mappingFunction.apply(key)) != null) {
                            added = true;
                            t.putTreeVal(h, key, val);
                        }
                    }
                }
            }
            if (binCount != 0) {
                if (binCount >= TREEIFY_THRESHOLD)
                    treeifyBin(tab, i);
                if (!added)
                    return val;
                break;
            }
        }
    }
    if (val != null)
        // 计数统计&阈值判断+扩容操作
        addCount(1L, binCount);
    return val;
}
```

好文推荐：

- [别再问我ConcurrentHashMap了](https://mp.weixin.qq.com/s?__biz=MzIwNTI2ODY5OA==&mid=2649938471&idx=1&sn=2964df2adc4feaf87c11b4915b9a018e&chksm=8f350992b842808477d2bfde6d58354f86c28b7a70d1c5395e550ed6ca683dadcbb7a9637775&token=512328060&lang=zh_CN#rd)
- [你的ThreadLocal线程安全么](https://mp.weixin.qq.com/s?__biz=MzIwNTI2ODY5OA==&mid=2649938424&idx=1&sn=e4b7d4d04b02794698f8b4d46a1d89d1&chksm=8f350a4db842835b7df97d6a42bab0cc25df1fef824be0427710643836bd47cd4fd91b5e562a&token=512328060&lang=zh_CN#rd)

![更多文章可扫描二维码](https://luoxn28.github.io/about/index/topcoder.png)

