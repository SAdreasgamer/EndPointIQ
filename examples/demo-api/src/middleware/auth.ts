export function authMiddleware(req: any, res: any, next: any) {
    const token = req.headers.authorization;
    if (!token) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    // TODO: actually validate the token
    next();
}
