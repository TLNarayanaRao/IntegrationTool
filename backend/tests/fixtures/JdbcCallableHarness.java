import java.lang.reflect.*;
import java.sql.*;
import java.util.*;
public class JdbcCallableHarness {
    static boolean registered,closed,timeout,prepared;
    static Object defaults(Class<?> type) { if(type==boolean.class)return false;if(type==int.class)return 0;if(type==long.class)return 0L;return null; }
    public static void main(String[] args) throws Exception {
        CallableStatement call=(CallableStatement)Proxy.newProxyInstance(JdbcCallableHarness.class.getClassLoader(),new Class[]{CallableStatement.class},(proxy,method,values)->{
            switch(method.getName()) {
                case "registerOutParameter":registered=values[0].equals(2)&&values[1].equals(Types.INTEGER);return null;
                case "setQueryTimeout":timeout=values[0].equals(3);return null;
                case "execute":return false;
                case "getUpdateCount":return -1;
                case "getObject":return 77;
                case "close":closed=true;return null;
                default:return defaults(method.getReturnType());
            }
        });
        Connection connection=(Connection)Proxy.newProxyInstance(JdbcCallableHarness.class.getClassLoader(),new Class[]{Connection.class},(proxy,method,values)->{
            if(method.getName().equals("prepareCall")){prepared=true;return call;}return defaults(method.getReturnType());
        });
        Properties p=new Properties();p.setProperty("sql","{call total(?,?)}");p.setProperty("operation","call");p.setProperty("queryTimeoutSeconds","3");p.setProperty("parameterCount","2");
        p.setProperty("parameter.0.type","integer");p.setProperty("parameter.0.value","4");p.setProperty("parameter.1.direction","OUT");p.setProperty("parameter.1.name","total");p.setProperty("parameter.1.declaredType","integer");
        Class<?> bridge=Class.forName("com.mina.bridge.MinaJavaBridge");Method execute=bridge.getDeclaredMethod("jdbcExecute",Connection.class,Properties.class);execute.setAccessible(true);
        Map<?,?> result=(Map<?,?>)execute.invoke(null,connection,p);
        if(!prepared||!registered||!closed||!timeout||!Integer.valueOf(77).equals(((Map<?,?>)result.get("outParameters")).get("total")))throw new AssertionError(result.toString());
        System.out.println("CallableStatement OUT, timeout and closure verified");
    }
}
