---
layout: blog
title: 深入理解ConcurrentHashMap
date: 2019-06-19 14:02:11
categories: [Java]
tags: [多线程]
toc: true
comments: true
---

以下ConcurrentHashMap以jdk8中为例进行分析，ConcurrentHashMap是一个线程安全、基于数组+链表(或者红黑树)的kv容器，主要特性如下：

- 线程安全，数组中单个slot元素个数超过8个时会将链表结构转换成红黑树，注意树节点之间还是有next指针的；
- 当元素个数超过N（`N = tab.length - tab.length>>>2，达到0.75阈值时`）个时触发rehash，成倍扩容；
- 当线程扩容时，其他线程put数据时会加入帮助扩容，加快扩容速度；
- put时对单个slot头节点元素进行synchronized加锁，ConcurrentHashMap中的加锁粒度是针对slot节点的，rehash过程中加锁粒度也是如此；
- get时一般是不加锁。如果slot元素为链表，直接读取返回即可；如果slot元素为红黑树，并且此时该树在进行再平衡或者节点删除操作，读取操作会按照树节点的next指针进行读取，也是不加锁的（因为红黑树中节点也是有链表串起来的）；如果该树并没有进行平衡或者节点删除操作，那么会用CAS加读锁，防止读取过程中其他线程该树进行更新操作（主要是防止破坏红黑树节点之间的链表特性），破坏“读视图”。

ConcurrentHashMap默认数组长度16，map最大容量为`MAXIMUM_CAPACITY = 1 << 30`。创建ConcurrentHashMap并不是涉及数组的初始化，数组初始化是在第一次put数据才进行的。（注意：JDK1.8中舍弃了之前的分段锁技术，改用CAS+Synchronized机制）

## Node结构

ConcurrentHashMap中一个重要的类就是Node，该类存储键值对，所有插入ConcurrentHashMap的数据都包装在这里面。它与HashMap中的定义很相似，但是有一些差别是ConcurrentHashMap的value和next属性都是volatile的（`保证了get数据时直接返回即可，volatile保证了更新的可见性`），且不允许调用setValue方法直接改变Node的value域，增加了find方法辅助map.get()方法，可在get方法返回的结果中更改对应的value值。

```java
static class Node<K,V> implements Map.Entry<K,V> {
    final int hash;
    final K key;
    volatile V val;
    volatile Node<K,V> next;
}
```

ConcurrentHashMap定义了三个原子操作，用于对数组指定位置的节点进行操作。正是这些原子操作保证了ConcurrentHashMap的线程安全。

```java
//获得在i位置上的Node节点  
static final <K,V> Node<K,V> tabAt(Node<K,V>[] tab, int i) {  
   return (Node<K,V>)U.getObjectVolatile(tab, ((long)i << ASHIFT) + ABASE);  
}  
//利用CAS算法设置i位置上的Node节点。之所以能实现并发是因为他指定了原来这个节点的值是多少  
//在CAS算法中，会比较内存中的值与你指定的这个值是否相等，如果相等才接受你的修改，否则拒绝你的修改  
//因此当前线程中的值并不是最新的值，这种修改可能会覆盖掉其他线程的修改结果
static final <K,V> boolean casTabAt(Node<K,V>[] tab, int i,  
                                   Node<K,V> c, Node<K,V> v) {  
   return U.compareAndSwapObject(tab, ((long)i << ASHIFT) + ABASE, c, v);  
}  
//利用volatile方法设置节点位置的值  
static final <K,V> void setTabAt(Node<K,V>[] tab, int i, Node<K,V> v) {  
   U.putObjectVolatile(tab, ((long)i << ASHIFT) + ABASE, v);  
}
```

下面就按照ConcurrentHashMap的 **put / get / remove** 来分析下其实现原理，中间涉及rehash、红黑树转换等。

## put流程

put操作流程如下：

- 首先根据key的hashCode计算hash，然后根据hash计算应该在数组中存储位置，如果数据为null，新建数组；
- 然后通过tabAt（&操作）直接获取对应slot。如果slot为null，则新建kv节点（Node类型）放到slot；
- 如果当前slot节点的hash值等于MOVED（等于-1），表示其类型为ForwardingNode，证明其他线程在进行rehash扩容操作，当前线程也会帮助一起进行扩容操作；
- 然后对slot节点进行synchronized加锁，如果slot节点hash值大于等于0，表示当前slot对应元素为链表结构，遍历当前链表，如果key存在则更新，否则添加到链表尾部；如果slot节点类型为TreeBin（其hash值为-2），表示slot对应元素为红黑树，则在红黑树中进行更新节点或者添加节点操作，注意，最后如果树不平衡会进行树的再平衡操作，此时对树root节点加CAS写锁。
- 最后，如果新添加了节点，会统计map size值；如果当前map数量超过了阈值（`N = tab.length - tab.length>>>2`）会触发rehash扩容，按照成倍扩容。

注意：因为往map中添加元素和增加元素统计值是两个步骤，不是原子的，所以获取map.size()时可能不是准确值。

**对key的hashCode计算hash**

存到map中的key并不是直接按照hashCode计算的，因为hashCode有可能为负的，并且不合理的hashCode实现可能导致较多冲突，因此ConcurrentHashMap中会对key对hashCode进行hash操作：

```java
// int hash = spread(key.hashCode());
// HASH_BITS = 0x7fffffff 符号位设置为0
static final int spread(int h) {
    return (h ^ (h >>> 16)) & HASH_BITS;
}
```

**红黑树节点比较**

既然使用到了红黑树，这就涉及到节点的大小比较问题（节点数据包含key、value信息）。进行节点的大小比较时，首先是比较节点的hash值，注意hash值不是hashCode，因为hash值是对象hashCode与自己无符号右移16位进行异或后的值。如果节点的hash值相等，判断节点的key对象是否实现了Comparable接口，实现的话就是用Comparable逻辑比较节点之间的大小。如果key对象未实现Comparable接口，则调用tieBreakOrder方法进行判断：

```java
// dir = tieBreakOrder(k, pk); k/pk，带比较两个节点，命名还是挺有意思的
static int tieBreakOrder(Object a, Object b) {
	int d;
	if (a == null || b == null ||
		(d = a.getClass().getName().
		 compareTo(b.getClass().getName())) == 0)
		d = (System.identityHashCode(a) <= System.identityHashCode(b) ?
			 -1 : 1);
	return d;
}
```

*这里调用了System.identityHashCode，将由默认方法hashCode()返回，如果对象的hashCode()被重写，则System.identityHashCode和hashCode()的返回值就不一样了。*

**put源码**

```java
final V putVal(K key, V value, boolean onlyIfAbsent) {
	// key value非空
	if (key == null || value == null) throw new NullPointerException();
	int hash = spread(key.hashCode());
	// slot对应元素个数，链表转换成红黑树时用
	int binCount = 0;
	for (Node<K,V>[] tab = table;;) {
		Node<K,V> f; int n, i, fh;
		if (tab == null || (n = tab.length) == 0)
			tab = initTable();
		else if ((f = tabAt(tab, i = (n - 1) & hash)) == null) {
			if (casTabAt(tab, i, null,
						 new Node<K,V>(hash, key, value, null)))
				break;                   // no lock when adding to empty bin
		}
		else if ((fh = f.hash) == MOVED)
			// 在rehash扩容，帮助扩容，扩容完成之后才能继续进行put操作
			tab = helpTransfer(tab, f);
		else {
			V oldVal = null;
			synchronized (f) { // 加锁
				if (tabAt(tab, i) == f) { // 可能已经被更新需要再次进行判断
					if (fh >= 0) { // 节点更新或插入
						binCount = 1;
						for (Node<K,V> e = f;; ++binCount) {
							K ek;
							if (e.hash == hash &&
								((ek = e.key) == key ||
								 (ek != null && key.equals(ek)))) {
								oldVal = e.val;
								if (!onlyIfAbsent)
									e.val = value;
								break;
							}
							Node<K,V> pred = e;
							if ((e = e.next) == null) {
								pred.next = new Node<K,V>(hash, key,
														  value, null);
								break;
							}
						}
					}
					else if (f instanceof TreeBin) { // 红黑树更新或插入
						Node<K,V> p;
						binCount = 2;
						if ((p = ((TreeBin<K,V>)f).putTreeVal(hash, key,
													   value)) != null) {
							oldVal = p.val;
							if (!onlyIfAbsent)
								p.val = value;
						}
					}
				}
			}
			if (binCount != 0) {
				if (binCount >= TREEIFY_THRESHOLD)
					treeifyBin(tab, i);
				if (oldVal != null)
					return oldVal;
				break;
			}
		}
	}
	// 增加统计值，可能触发rehash扩容
	addCount(1L, binCount);
	return null;
}

private final void addCount(long x, int check) {
	CounterCell[] as; long b, s;
	/**
	 * counterCells非空表示当前put并发较大，按照counterCells进行分线程统计
	 * 参考LongAddr思想
	 */
	if ((as = counterCells) != null ||
		!U.compareAndSwapLong(this, BASECOUNT, b = baseCount, s = b + x)) {
		CounterCell a; long v; int m;
		boolean uncontended = true;
		if (as == null || (m = as.length - 1) < 0 ||
			(a = as[ThreadLocalRandom.getProbe() & m]) == null ||
			!(uncontended =
			  U.compareAndSwapLong(a, CELLVALUE, v = a.value, v + x))) {
			fullAddCount(x, uncontended);
			return;
		}
		if (check <= 1)
			return;
		s = sumCount();
	}
	if (check >= 0) {
		Node<K,V>[] tab, nt; int n, sc;
		// 大于等于阈值数时进行扩容操作
		while (s >= (long)(sc = sizeCtl) && (tab = table) != null &&
			   (n = tab.length) < MAXIMUM_CAPACITY) {
			int rs = resizeStamp(n);
			if (sc < 0) {
				if ((sc >>> RESIZE_STAMP_SHIFT) != rs || sc == rs + 1 ||
					sc == rs + MAX_RESIZERS || (nt = nextTable) == null ||
					transferIndex <= 0)
					break;
				if (U.compareAndSwapInt(this, SIZECTL, sc, sc + 1))
					transfer(tab, nt);
			}
			else if (U.compareAndSwapInt(this, SIZECTL, sc,
										 (rs << RESIZE_STAMP_SHIFT) + 2))
				transfer(tab, null);
			s = sumCount();
		}
	}
}
```

## get流程

get方法比较简单，给定一个key来确定value的时候，必须满足两个条件hash值相同同时 key相同（equals） ，对于节点可能在链表或树上的情况，需要分别去查找。

get时一般是不加锁（Node节点中value数据类型是volatile的，保证了内存可见性）。如果slot元素为链表，直接读取返回即可；如果slot元素为红黑树，并且此时该树在进行再平衡或者节点删除操作，读取操作会按照树节点的next指针进行读取，也是不加锁的；如果该树并没有进行平衡或者节点删除操作，那么会用CAS加读锁，防止读取过程中其他线程该树进行更新操作，破坏“读视图”。

## remove流程

remove流程就是根据key找到对应节点，将该节点从链表（更改节点前后关系）或者红黑树移除的过程，注意，从红黑树中删除元素后，不会将红黑树转换为列表的，只能在put元素时列表可能有转换红黑树操作，不会有反向操作。

注意：hashMap有自动rehash扩容机制，但是当元素remove之后并没有自动缩容机制，如果数组经过多次扩容变得很大，并且当前元素较少，请将这些元素转移到一个新的HashMap中。

## rehash流程

rehash时是成倍扩容（老table和新tableNew），对于table中i位置的所有元素，扩容后会被分配到i和i+table.length这两个位置中。rehash主要的流程transfer方法中，具体不再展开。