---
layout: blog
title: influxdb的命令们
date: 2020-01-28 17:35:08
categories: []
tags: [influxdb]
toc: true
comments: true
---

> InfluxDB是一个开源的时序数据库，使用GO语言开发，特别适合用于处理和分析资源监控数据这种时序相关数据。而InfluxDB自带的各种特殊函数如求标准差，随机取样数据，统计数据变化比等，使数据统计和实时分析变得十分方便。

influxdb的单机版是开源的，而集群版是商业版，influxdb被设计运行在SSD上，如果使用机器或者网络磁盘作为存储介质，会导致性能下降至少一个数量级。influxdb支持restful api，同时也支持https，为了保证安全性，非局域网建议使用https与Influxdb进行通信。

> 学习influxdb，如同学习MySQL先要了解SQL一样，让我们一起来看看influxdb的那些命令们 ~

centos下使用命令 yum install influxdb 安装influxdb之后，就可以使用命令 service influxdb start 启动influxdb，通过命令 influx 启动cli客户端。influxdb的命令基本都符合标准的sql格式，基础操作命令如下：

```sql
influx 启动influxdb客户端，如同mysql -u xxx功能
create database db1  创建数据库db1
show databases  查看数据库列表
use db1  使用数据库db1，是不是和mysql中功能类似
show measurements  查看measurement列表

drop database db1  删除数据库db1
drop measurement mt1  删除表mt1
delete from measurement [WHERE <tag_key> <operator>]
drop shard <shard_id_num> 删除分片
```

### influxdb的概念们

- **database**：数据库；
- **measurement**：数据表；
- **point**：数据行，由时间戳、tag、field组成（`一条数据至少包括measurement（对应mysql中表概念）、timestamp、至少一个k-v结构的field，再加上0个或者多个k-v结构的tag`）；
- **series**：一些数据结合，同一个database下，`retention policy、measurement、tag sets `完全相同的数据同属于一个 series，同一个series的数据物理上会存放在一起；
- **分片**：默认按时间段创建的数据分片，它和存储策略相关，每一个存储策略下会存在许多 shard，每一个 shard 存储一个指定时间段内的数据，并且不重复。每一个分片都映射到底层存储引擎数据库，每一个数据库都有自己的WAL和TSM文件，使用命令 show shards 查看分片。

influxdb数据写入需满足如下格式：

```sql
insert <measurement>[,<tag-key>=<tag-value>...] <field-key>=<field-value>[,<field2-key>=<field2-value>...] [unix-nano-timestamp] 
```

> 注意：measurement和至少一个fileld的k-v是必须的，tag和timestrap时间戳是可选的。

说实话，这个写入格式还是有点小严格的，因为它要求measurement和可能的0个或多个tag之间必须是紧挨着的，中间不能有空格；同时多个filed之间也是不能有空格，tag和field的k，tag的v都是字符串类型；时间戳不是必须的，如果为空则使用服务端的本地时间作为时间戳。相同时间戳的数据第二次写入会覆盖第一次写入的数据，相当于更新操作。

数据写入完成之后，就可以使用查看命令：

```sql
select * from measurement_name [WHERE <tag_key> <operator>] [limit xx]  查看数据
show series [on dbname] [from measurement] [WHERE <tag_key> <operator>] [limit xx]  查看series信息
show tag keys [on dbname] [from measurement] [WHERE <tag_key> <operator>] [limit xx]  查看tag keys信息
show field keys [on dbname] [from measurement]  查看field keys
```

Influxdb可支持每秒十万级别的数据量，如果长时间保存会对存储造成很大压力，因此和一般数据存储系统一样有一个数据保留策略，同时针对大流量量数据可采样保存，小流量数据可全量保存。influxdb通过保留策略（`RP，Retention Policy`）来管理过期数据。

```sql
# 创建过期策略
create retention policy <retention_policy_name> on <database_name> duration <duration> replicationN <n> [SHARD DURATION <duration>] [DEFAULT]
show retention policies [on dbname]  查看过期策略
```

在influxdb中，通过数据保留策略（RP），分片是挂在RP下管理的，数据过期的维度是分片，当检测到一个 shard 中的数据过期后，只需要将这个 shard 的资源释放，相关文件删除即可，这样的做法使得删除过期数据变得非常高效。

除了直接使用influxdb命令之外，还可使用函数，influxdb的函数大致分为`aggregate，select和predict`。**aggregate类型命令大致如下**：

- **count：**返回非空字段数据数量，格式为` select count ( [ * | <field_key> | /<regular_expression>/ ] ) from measurement_name [WHERE <tag_key> <operator>] [limit xx] `。除了统计非空字段数量之外，还可统计distinct列的数量，比如命令 `select count(distintct("xxx")) from xxx`。大多数influxdb命令针对没有数据间隔返回null，count针对没有数据返回的间隔返回0，而类似的`fill(<fill_option>)`用fill_option替换0值。
- **distinct**：返回非null值的数据不相同数据计数。
- **integral**：返回曲线下面积（积分），格式为 `select integral ( [ * | <field_key> | /<regular_expression>/ ] [ , <unit> ]  ) from measurement_name [WHERE <tag_key> <operator>] [limit xx]` ，uint为时间单位，默认单位s。
- **mean**：返回字段平均值。
- **median**：返回字段中位数。
- **mode**：返回字段中出现频率最高的值。
- **spread**：返回字段中最大值、最小值的差值。
- **stddev**：返回字段的标准差。
- **sum**：字段和。

**selectors类型命令大致如下**：

- **bottom**：返回最小的n个值，格式为` select bottom (<field_key>[,<tag_key(s)>],<N> ) from xxx where xxx`；
- **first**：返回时间戳最早的值；
- **last**：返回时间戳最近的值；
- **max、min**：返回最大/最小返回值；
- **percentile**：返回较大的百分比，格式为` select percentile (<field_key>, <N>)[,<tag_key(s)>|<field_key(s)>]`；
- **top**：返回最大的字段值。

influxdb支持很多常见和高级的聚合查询函数，可满足大多数场景需要，具体可参考 https://jasper-zhang1.gitbooks.io/influxdb/content/Query_language/functions.html。

### 小结

infludb中存储的是时间序列数据，比如说某个时间点系统负载、服务耗时等信息，时间序列数据可以包含多个值。关于什么是时间序列数据，简单来来说就是数据是和一个时间点关联的，结合mysql中的记录与id关系来看就是时间序列数据的主键就是时间点（`timestrap`）。

infludb中的一条数据至少包括`measurement`（对应mysql中表概念）、`timestamp`、至少`一个k-v结构的field`，再加上0个或者多个k-v结构的tag。对比mysql来看，measurement就是一张表，其主键是timestamp时间戳，tag和field对应就是表中列，tag和field都是k-v接口，k对应列的名字，v对应该列存储的值，tag和field不同的是，tag是有索引的而field没有（如果查询条件为tag则会扫描所有查询到的数据），对于mysql表的有索引列和无索引列。注意mysql中的表需要提前定义结构，而influxdb中的measurement无需提前定义，其null值也不会被存储。

influxdb中measurement无需定义，即无模式设计，开发者可以在任意添加measurement，tags和fields，不过针对同一个field，第二次和第一次写入的数据类型不匹配，influxdb会报错（由于默认tag的v都是字符串类型，所有不存在这个问题，不管输入是什么数据都当做字符串来处理）。