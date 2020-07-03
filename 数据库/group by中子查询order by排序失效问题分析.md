---
layout: blog
title: group by中子查询order by排序失效问题分析
date: 2020-03-17 17:24:25
categories: [数据库]
tags: [mysql]
toc: true
comments: true
---

> 通过sql分组查询数据时，一般通过group by来完成，group by默认取相同的分组列(一列或者多列)中第一个数据。

如果想获取sql分组中id最大的记录，我们可能想到的sql如下（name列作为分组）：

```sql
select id,name from (select id,name from tt order by id desc) as t group by name
```

不过执行该sql发现并不能达到我们的目的，输出数据如下：

```sql
// 表数据如下：
id,name
1,name1
2,name1
3,name2
4,name2

select id,name from (select id,name from tt order by id desc) as t group by name
// 输出结果如下：
id,name
1,name1
3,name2
```

这是为什么呢？**因为mysql 5.6之后版本对排序的sql解析做了优化，子查询中的排序是会被忽略的，所以上面的order by id desc未起到作用。**如果子语句中排序不做优化那不就可以了么，查阅资料发现可以在子语句中加上limit来避免这种优化（加上limit相当于临时表限定了取值范围不会进行优化，如果是全表的话就被优化掉了）。

```sql
// 加上limit
select id,name from (select id,name from tt order by id desc limit 1024) as t group by name

// 输出结果如下：
id,name
2,name1
4,name2
```

除了上述这种直接通过group by分组得到id最大记录之外，还可以通过分组获取到最大记录id，然后通过id获取对应记录（这里的id只要是记录的关键key即可）。

```sql
// 通过分组获取关键key，然后再获取对应记录
select id,name from tt where id in (select max(id) from tt group by name)

// 输出结果如下：
id,name
2,name1
4,name2
```

其实除了group by获取分组最后一个记录之外，还可以通过关联子查询方式来实现：

```sql
select id,name from tt a where id = (select max(id) from tt where name = a.name) order by name

// 输出结果如下
id,name
2,name1
4,name2
```

通过以上group by和关联子查询两种方式的实现，获取分组的最后一条记录要么直接通过分组直接来获取，要么先获取到记录关键key然后通过关键key获取对应的记录即可。