# 代码执行器插件新功能说明

## 新增配置项

### 1. 本地路由发送功能

**配置项**: `enable_local_route_sending`
- **类型**: 布尔值 (bool)
- **默认值**: `false`
- **说明**: 启用后将把文件挂载到本地路由进行网络文件发送，适用于AstrBot和发送框架不在同一网络的情况

**工作原理**:
- 当启用本地路由发送时，插件会通过WebUI服务器提供文件URL
- 文件通过 `http://{local_route_host}:{webui_port}/files/{filename}` 路径访问
- 插件将文件URL直接传递给AstrBot的文件发送功能，支持图片和普通文件
- 对于图片文件，使用 `MessageChain().file_image(url)` 发送
- 对于普通文件，使用 `Comp.File(file=url, name=filename)` 发送

**安全特性**:
- 只允许访问配置的输出目录内的文件
- 包含路径遍历攻击防护
- 文件访问权限严格控制

### 2. Lagrange服务器IP配置

**配置项**: `lagrange_host`
- **类型**: 字符串 (string)
- **默认值**: `"127.0.0.1"`
- **说明**: Lagrange服务器的IP地址，默认为127.0.0.1（本地），如果AstrBot和Lagrange不在同一主机请填写Lagrange的IP地址

### 3. 本地路由主机配置

**配置项**: `local_route_host`
- **类型**: 字符串 (string)
- **默认值**: `"localhost"`
- **说明**: 配置本地路由发送时使用的主机IP地址，设置文件服务的主机地址，支持局域网IP以便Docker等环境访问

**使用场景**:
- 当AstrBot和Lagrange部署在不同服务器时
- 需要跨网络访问Lagrange服务时
- 支持远程Lagrange实例

## 文件发送优先级

插件现在支持三种文件发送方式，按以下优先级尝试发送，如果前一种方式失败会自动尝试下一种：

1. **本地路由发送** (`enable_local_route_sending = true`)
   - 优先尝试
   - 通过WebUI提供文件下载链接
   - 适用于跨网络场景

2. **Lagrange适配器** (`enable_lagrange_adapter = true`)
   - 本地路由失败时尝试
   - 通过Lagrange API上传文件
   - 支持远程Lagrange服务器

3. **AstrBot原生方式** (默认)
   - 前两种都失败时使用
   - 使用AstrBot框架自带的文件发送功能
   - 适用于标准部署场景

**容错机制**: 如果某种发送方式失败，系统会自动尝试下一种可用的发送方式，确保文件能够成功发送。

## 配置示例

### 启用本地路由发送
```json
{
  "enable_local_route_sending": true,
  "local_route_host": "192.168.1.50",
  "webui_port": 22334,
  "output_directory": "/path/to/output"
}
```

### 配置远程Lagrange服务器
```json
{
  "enable_lagrange_adapter": true,
  "lagrange_host": "192.168.1.100",
  "lagrange_api_port": 8083
}
```

### 同时启用两种方式（本地路由优先）
```json
{
  "enable_local_route_sending": true,
  "enable_lagrange_adapter": true,
  "lagrange_host": "192.168.1.100",
  "lagrange_api_port": 8083,
  "webui_port": 22334
}
```

## 日志信息

插件启动时会显示当前的文件发送配置状态：

```
本地路由发送已启用，文件服务地址: http://localhost:22334/files/
Lagrange适配器已启用，服务地址: 192.168.1.100:8083
```

或者：

```
使用AstrBot原生文件发送方式
```

## 注意事项

1. **本地路由发送**需要确保WebUI端口可以被目标用户访问
2. **Lagrange配置**需要确保网络连通性和API可用性
3. **安全性**：本地路由发送只允许访问配置的输出目录内的文件
4. **优先级**：如果同时启用多种发送方式，会按优先级选择使用

## 兼容性

- 新功能完全向后兼容
- 不影响现有配置和功能
- 默认情况下使用原有的AstrBot原生发送方式