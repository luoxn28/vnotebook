---
layout: blog
title: ToString如何反序列化
date: 2020-03-08 17:24:25
categories: [Java]
tags: []
toc: true
comments: true
---

不知道小伙伴们有没有这样的困扰，平常开发中写单测，要mock一个复杂的对象，并且也知道了该对象的toString格式数据（比如从日志中获取），但是该怎么构建这个对象呢？

> 如果是json格式可以直接通过json反序列化得到对象，那么toString格式如何反序列得到对象呢？

从反序列化原理来看，我们首先要解析出对象的一个个属性，toString对象属性格式为 `k1=v1,k2=v2` ，那么可以按照逗号 `,` 作为分隔符解析出一个个token，注意一个token可以是基本类型的kv，比如 `int/Interger/…/String` 这种；也可以是对象类型，比如 `object/array/list/map` 等。解析出来token之后，基本类型的token可以直接通过反射将v设置到对象属性（Field）中；对象类型的token可以继续按照toString格式进行反序列化，直到全部数据都反序列化成功为止；针对 `array/list/map` 的数据要获取到对应元素的实际类型才能知道要反序列化的对象。对应的代码实现如下：

```java
/**
 * toString格式反序列化类
 *
 * @author luoxiangnan
 * @date 2020-03-02
 */
public class ToStringUtils {

    /**
     * toString格式反序列化
     */
    @SuppressWarnings("all")
    public static <T> T toObject(Class<T> clazz, String toString) throws Exception {
        if (Objects.isNull(clazz) || Objects.isNull(toString) || StringUtils.isEmpty(toString)) {
            return clazz == String.class ? (T) toString : null;
        } else if (TypeValueUtils.isBasicType(clazz)) {
            return (T) TypeValueUtils.basicTypeValue(clazz, toString.trim());
        }

        toString = TokenUtils.cleanClassPrefix(clazz, toString.trim());
        toString = StringUtils.removeStart(toString, "(").trim();
        toString = StringUtils.removeEnd(toString, ")").trim();

        String token = null;
        T result = clazz.newInstance();
        while (StringUtils.isNotEmpty(toString) && StringUtils.isNotEmpty(token = TokenUtils.splitToken(toString))) {
            toString = StringUtils.removeStart(StringUtils.removeStart(toString, token).trim(), ",").trim();

            // 解析k/v格式的属性名/值
            Pair<String, String> keyValue = TokenUtils.parseToken(token);
            Field field = FieldUtils.getField(clazz, keyValue.getKey(), true);
            Object value = TypeValueUtils.buildTypeValue(field, keyValue.getValue());
            FieldUtils.writeField(field, result, value, true);
        }
        return result;
    }

    /**
     * 字符串解析类
     */
    static class TokenUtils {

        /**
         * 清除类名前缀字符串
         */
        static String cleanClassPrefix(Class clazz, String toString) {
            String simpleName = clazz.getSimpleName();
            if (clazz.getName().contains("$")) {
                // 内部类需要按照内部类名字格式
                String rowSimpleName = StringUtils.substringAfterLast(clazz.getName(), ".");
                simpleName = StringUtils.replace(rowSimpleName, "$", ".");
            }
            return toString.startsWith(simpleName) ?
                    StringUtils.removeStart(toString, simpleName).trim() : toString;
        }

        /**
         * 获取第一个token，注意: toString不再包括最外层的()
         */
        private final static Map<Character, Character> tokenMap = new HashMap<>();
        static {
            tokenMap.put(')', '(');
            tokenMap.put('}', '{');
            tokenMap.put(']', '[');
        }

        static String splitToken(String toString) {
            if (StringUtils.isBlank(toString)) {
                return toString;
            }

            int bracketNum = 0;
            Stack<Character> stack = new Stack<>();
            for (int i = 0; i < toString.length(); i++) {
                Character c = toString.charAt(i);
                if (tokenMap.containsValue(c)) {
                    stack.push(c);
                } else if (tokenMap.containsKey(c) && Objects.equals(stack.peek(), tokenMap.get(c))) {
                    stack.pop();
                } else if ((c == ',') && stack.isEmpty()) {
                    return toString.substring(0, i);
                }
            }
            if (stack.isEmpty()) {
                return toString;
            }
            throw new RuntimeException("splitFirstToken error, bracketNum=" + bracketNum + ", toString=" + toString);
        }

        /**
         * 从token解析出字段名，及对应值
         */
        static Pair<String, String> parseToken(String token) {
            assert Objects.nonNull(token) && token.contains("=");
            int pos = token.indexOf("=");
            return new javafx.util.Pair<>(token.substring(0, pos), token.substring(pos + 1));
        }
    }

    /**
     * 对象构建类
     */
    static class TypeValueUtils {

        static Set<Class> BASIC_TYPE = Stream.of(
                char.class, Character.class,
                boolean.class, Boolean.class,
                short.class, Short.class,
                int.class, Integer.class,
                float.class, Float.class,
                double.class, Double.class,
                long.class, Long.class,
                String.class).collect(Collectors.toSet());

        /**
         * Filed类型是否为基础类型
         */
        static boolean isBasicType(Class clazz) {
            return BASIC_TYPE.contains(clazz);
        }

        @SuppressWarnings("all")
        static Object buildTypeValue(Field field, String value) throws Exception {
            if (StringUtils.isBlank(value) || "null".equalsIgnoreCase(value)) {
                return field.getType() == String.class ? value : null;
            }

            Class clazz = field.getType();
            if (isBasicType(clazz)) {
                return basicTypeValue(field.getGenericType(), value);
            } else if (field.getGenericType() == Date.class) {
                return new SimpleDateFormat("EEE MMM dd HH:mm:ss Z yyyy", new Locale("us")).parse(value);
            } else if (clazz.isArray() || clazz.isAssignableFrom(Array.class)) {
                return arrayTypeValue(field.getType().getComponentType(), value);
            } else if (clazz.isAssignableFrom(List.class)) {
                return listTypeValue(field, value);
            } else if (clazz.isAssignableFrom(Map.class)) {
                return mapTypeValue(field, value);
            } else {
                return toObject(clazz, value);
            }
        }

        static Object basicTypeValue(Type type, String value) {
            if (type == Character.class || type == char.class) {
                return value.charAt(0);
            } else if (type == Boolean.class || type == boolean.class) {
                return Boolean.valueOf(value);
            } else if (type == Short.class || type == short.class) {
                return Short.valueOf(value);
            } else if (type == Integer.class || type == int.class) {
                return Integer.valueOf(value);
            } else if (type == Float.class || type == float.class) {
                return Float.valueOf(value);
            } else if (type == Double.class || type == double.class) {
                return Double.valueOf(value);
            } else if (type == Long.class || type == long.class) {
                return Long.valueOf(value);
            } else if (type == String.class) {
                return value;
            }
            throw new RuntimeException("basicTypeValue error, type=" + type + ", value=" + value);
        }

        @SuppressWarnings("unchecked")
        static Object listTypeValue(Field field, String fieldValue) throws Exception {
            fieldValue = StringUtils.removeStart(fieldValue, "[").trim();
            fieldValue = StringUtils.removeEnd(fieldValue, "]").trim();

            String token;
            List<Object> result = new ArrayList<>();
            while (StringUtils.isNotEmpty(fieldValue) && StringUtils.isNotEmpty(token = TokenUtils.splitToken(fieldValue))) {
                fieldValue = StringUtils.removeStart(StringUtils.removeStart(fieldValue, token).trim(), ",").trim();
                result.add(toObject((Class) ((ParameterizedType) field.getGenericType()).getActualTypeArguments()[0], token));
            }
            return result;
        }

        @SuppressWarnings("unchecked")
        static <T> T[] arrayTypeValue(Class<?> componentType, String fieldValue) throws Exception {
            fieldValue = StringUtils.removeStart(fieldValue, "[").trim();
            fieldValue = StringUtils.removeEnd(fieldValue, "]").trim();

            String token;
            T[] result = newArray(componentType, fieldValue);
            for (int i = 0; StringUtils.isNotEmpty(fieldValue) && StringUtils.isNotEmpty(token = TokenUtils.splitToken(fieldValue)); i++) {
                fieldValue = StringUtils.removeStart(StringUtils.removeStart(fieldValue, token).trim(), ",").trim();
                result[i] = (T) toObject(componentType, token);
            }
            return result;
        }

        private static <T> T[] newArray(Class<?> componentType, String fieldValue) {
            String token;
            int lengh = 0;
            while (StringUtils.isNotEmpty(fieldValue) && StringUtils.isNotEmpty(token = TokenUtils.splitToken(fieldValue))) {
                fieldValue = StringUtils.removeStart(StringUtils.removeStart(fieldValue, token).trim(), ",").trim();
                lengh++;
            }

            return (T[]) Array.newInstance(componentType, lengh);
        }

        @SuppressWarnings("unchecked")
        static Map mapTypeValue(Field field, String toString) throws Exception {
            toString = StringUtils.removeStart(toString, "{").trim();
            toString = StringUtils.removeEnd(toString, "}").trim();

            String token;
            Map result = new HashMap();
            while (StringUtils.isNotEmpty(token = TokenUtils.splitToken(toString))) {
                toString = StringUtils.removeStart(StringUtils.removeStart(toString, token).trim(), ",").trim();
                assert token.contains("=");
                String fieldName = StringUtils.substringBefore(token, "=").trim();
                String fieldValue = StringUtils.substringAfter(token, "=").trim();

                result.put(basicTypeValue(((ParameterizedType) field.getGenericType()).getActualTypeArguments()[0], fieldName),
                        toObject((Class) ((ParameterizedType) field.getGenericType()).getActualTypeArguments()[1], fieldValue));

            }
            return result;
        }
    }
}
```

测试代码如下：

```java
public class ToStringUtilsTest {

    @Test
    public void toObject() throws Exception {
        DemoBean demoBean = DemoBean.builder()
                .c1('c').c2('d').s1((short) 1).s2((short) 2)
                .i1(1).i2(2).l1(1L).l2(2L)
                .f1(1.0F).f2(2.0F).d1(1.0D).d2(2.0D)
                .ss1("").ss2("null").date(new Date())
                .a(new A()).aList(Arrays.asList(new A(), new A()))
                .aArray((A[]) Arrays.asList(new A(), new A()).toArray())
                .build();
        {
            Map<String, A> aMap = new HashMap<>();
            aMap.put("1", new A());
            aMap.put("2", new A());
            aMap.put("3", new A());
            demoBean.setAMap(aMap);
        }
        String toString = demoBean.toString();

        DemoBean demoBean2 = ToStringUtils.toObject(DemoBean.class, toString);
        System.out.println(demoBean2);
        Assert.assertEquals(toString, demoBean2.toString());
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    static class DemoBean {
        private char c1;
        private Character c2;
        private short s1;
        private Short s2;
        private int i1;
        private Integer i2;
        private long l1;
        private long l2;
        private float f1;
        private Float f2;
        private double d1;
        private double d2;
        private String ss1;
        private String ss2;
        private String ss3 = null;
        private Date date;

        private A a;
        private List<A> aList;
        private A[] aArray;

        private Map<String, A> aMap;
    }

    @Data
    static class A {
        private static int num = 1;

        private int i = 11 + num++;
        private Long l = 22L + num++;
        private Date date = new Date(System.currentTimeMillis() + num++);
    }
}
```

结果输出如下：

```java
ToStringUtilsTest.DemoBean(c1=c, c2=d, s1=1, s2=2, i1=1, i2=2, l1=1, l2=2, f1=1.0, f2=2.0, d1=1.0, d2=2.0, ss1=, ss2=null, ss3=null, date=Sun Mar 08 09:44:52 CST 2020, a=ToStringUtilsTest.A(i=12, l=24, date=Sun Mar 08 09:44:52 CST 2020), aList=[ToStringUtilsTest.A(i=15, l=27, date=Sun Mar 08 09:44:52 CST 2020), ToStringUtilsTest.A(i=18, l=30, date=Sun Mar 08 09:44:52 CST 2020)], aArray=[ToStringUtilsTest.A(i=21, l=33, date=Sun Mar 08 09:44:52 CST 2020), ToStringUtilsTest.A(i=24, l=36, date=Sun Mar 08 09:44:52 CST 2020)], aMap={1=ToStringUtilsTest.A(i=27, l=39, date=Sun Mar 08 09:44:52 CST 2020), 2=ToStringUtilsTest.A(i=30, l=42, date=Sun Mar 08 09:44:52 CST 2020), 3=ToStringUtilsTest.A(i=33, l=45, date=Sun Mar 08 09:44:52 CST 2020)})
```

`ToStringUtils` 针对大部分场景的toString反序列化是OK的，但是针对map中key是对象类型这种场景还未支持，感兴趣的小伙伴可以自行按照上述代码进行扩展，源码地址为：https://github.com/luoxn28/code-toolbox/blob/master/java/src/main/java/com/github/nan/util/ToStringUtils.java。