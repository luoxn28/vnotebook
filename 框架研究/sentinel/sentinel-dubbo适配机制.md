---
layout: blog
title: sentinel dubbo适配机制
date: 2019-06-29 15:50:06
categories: [框架研究]
tags: [sentinel]
toc: true
comments: true
---

sentinel针对目前常见的主流框架都做了适配，比如dubbo、Web Servlet、Spring Cloud、Spring WebFlux等。sentinel的适配做到了开箱即用，那么它是通过什么机制来实现的呢？这里大家可以思考下，如果一个框架本身没有扩展机制（这只是举个极端的例子，一般开源框架都是有自身的扩展机制的），那么sentinel是无法进行适配的，更谈不上开箱即用，除非更改框架源码。所以说，如果明白了框架的扩展机制，那么理解sentinel的适配机制就很easy了，比如dubbo 本身有Filter机制（consumer端和provider端都有），Web servlet也有自己的Filter机制可进行自定义扩展。

关于sentinel dubbo的使用示例，因为官方文档已经有详细说明了，这里不再赘述了。下面主要分析sentinel dubbo的实现原理。

因为dubbo提供有Filter机制，默认需要在 META-INF\dubbo\org.apache.dubbo.rpc.Filter文件中进行配置，sentinel dubbo的配置如下：

```properties
sentinel.dubbo.provider.filter=com.alibaba.csp.sentinel.adapter.dubbo.SentinelDubboProviderFilter
sentinel.dubbo.consumer.filter=com.alibaba.csp.sentinel.adapter.dubbo.SentinelDubboConsumerFilter
dubbo.application.context.name.filter=com.alibaba.csp.sentinel.adapter.dubbo.DubboAppContextFilter
```

此处可见，consumer端和provider端各对应一个filter类，这里以SentinelDubboProviderFilter为例进行分析：

```java
@Activate(group = "provider")
public class SentinelDubboProviderFilter implements Filter {
    @Override
    public Result invoke(Invoker<?> invoker, Invocation invocation) throws RpcException {
        // Get origin caller.
        String application = DubboUtils.getApplication(invocation, "");

        Entry interfaceEntry = null;
        Entry methodEntry = null;
        try {
            // resourceName格式为 "接口:方法(入参1,入参2)"
            String resourceName = DubboUtils.getResourceName(invoker, invocation);
            String interfaceName = invoker.getInterface().getName();
            // Only need to create entrance context at provider side, as context will take effect
            // at entrance of invocation chain only (for inbound traffic).
            // 以resourceName作为context name
            ContextUtil.enter(resourceName, application);
            interfaceEntry = SphU.entry(interfaceName, EntryType.IN);
            methodEntry = SphU.entry(resourceName, EntryType.IN, 1, invocation.getArguments());

            Result result = invoker.invoke(invocation);
            if (result.hasException()) {
                Throwable e = result.getException();
                // Record common exception.
                Tracer.traceEntry(e, interfaceEntry);
                Tracer.traceEntry(e, methodEntry);
            }
            return result;
        } catch (BlockException e) {
            return DubboFallbackRegistry.getProviderFallback().handle(invoker, invocation, e);
        } catch (RpcException e) {
            Tracer.traceEntry(e, interfaceEntry);
            Tracer.traceEntry(e, methodEntry);
            throw e;
        } finally {
            if (methodEntry != null) {
                methodEntry.exit(1, invocation.getArguments());
            }
            if (interfaceEntry != null) {
                interfaceEntry.exit();
            }
            ContextUtil.exit();
        }
    }
}
```

SentinelDubboProviderFilter中会对两个维度进行SphU.entry操作：

- 接口维度：resouce name为interfaceName；
- 方法维度：resouce name为方法签名，格式为 "接口:方法(入参1,入参2)"。

处理流程是，先获取接口维度的Resource，再获取方法维度的Resource，二者都获取成功之后，再执行后续的dubbo invoker操作，也就是后续的RPC处理。通过接口和方法两个不同维度，在provider端进行流控更加灵活。

> 看到这块代码时，笔者有一个疑问：

针对dubbo provider端的流控，SentinelDubboProviderFilter.invoke方法中会先对interfaceName做SphU.entry操作，然后在对method签名做SphU.entry操作，二者通过后再执行invoke后续操作。因为二者不是原子的，有可能针对interfaceName的pass，但是针对method签名的blocked，但是这个时候已经增加了interfaceName对应的pass统计值，这样同一个时间窗口内会影响到针对该接口其他方法的dubbo rpc调用。目前从代码来看，sentinel并未处理这种情况，因为目前没有针对资源的统计值做decrement功能。

试下一下，如果需要解决该问题，应该如何做呢？

- 方案一：增加一个统计值decrement功能，如果针对method签名执行SphU.entry操作被blocked时，调用统计值decrement功能，撤销之前相同时间窗口内针对interfaceName的pass值；
- 方案二：像这种需要针对两个resource做SphU.entry操作的场景，可以在判断是否通过pass时同时判断这两个resource对应的统计值是否满足规则限制，让这两个Resource产生关联，一同判断即可。

笔者倾向于方案二的实现，其实现流程和单个Resource的类似（只不过新增个Resource判断条件），而不像方案一那样需要提供新的方法+增加撤销逻辑来满足，严格来讲，方案一在对资源申请和撤销操作之间，也是会暂用一个pass名额的。