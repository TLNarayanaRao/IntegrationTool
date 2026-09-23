package fixture;

// Contract fixture only: no external broker or vendor library required.
public class FakeJmsFactory {
    static int connections, producers, sends;
    public FakeJmsFactory(String url) {}
    public Connection createConnection(String user, String password) { connections++; return new Connection(); }
    public static class Connection {
        public void start() {}
        public void setClientID(String id) {}
        public Session createSession(boolean transacted, int mode) { return new Session(); }
        public void close() {}
    }
    public static class Session {
        public Object createQueue(String name) { return name; }
        public Object createTopic(String name) { return name; }
        public Producer createProducer(Object destination) { producers++; return new Producer(); }
        public Message createTextMessage(String body) { return new Message(body); }
        public void close() {}
    }
    public static class Message {
        String body, id;
        public Message(String body) { this.body = body; }
        public void setJMSCorrelationID(String id) {}
        public void setJMSType(String type) {}
        public void setJMSReplyTo(Object destination) {}
        public void setStringProperty(String name, String value) {}
        public String getJMSMessageID() { return id; }
    }
    public static class Producer {
        int mode, priority; long ttl;
        public void setDeliveryMode(int value) { mode = value; }
        public void setPriority(int value) { priority = value; }
        public void setTimeToLive(long value) { ttl = value; }
        public void send(Message message) {
            if (message.body.equals("FAIL")) throw new IllegalStateException("simulated provider failure");
            message.id = connections + ":" + producers + ":" + (++sends) + ":" + mode + ":" + priority + ":" + ttl + ":" + message.body;
        }
        public void close() {}
    }
}
